# 実装ノート

開発指示書 v0.4（[persona-layer-spec.md](persona-layer-spec.md)）に対する本実装の対応関係と、
仕様が実装に委ねた点についての判断記録。

## 実装言語・構成

- **Python 3.10+**（pydantic v2 / FastAPI / asyncio）。仕様書の TypeScript 記法は
  データモデル定義として読み、JSON 表現（camelCase）を正として互換を取った。
  `manifest.json` は仕様書 §4.2 のフィールド名と完全一致する
- §5.1 文言表・§5.3 prosody 表・§8.1 表情マップ・§11.6 調停パラメータは
  `src/persona_layer/tables/*.yaml` の**設定テーブル**として持つ（§8.1 のテーブル駆動要件）。
  チューニングはこのファイル群だけを触ればよく、コード変更・再ビルド不要（§14）

## フェーズ対応

| Phase | 実装 | 完了条件の状況 |
|---|---|---|
| 1 | `models.py` + `composers.py` + `tables/style_prompts.yaml` | 基準3・4は盲検素材生成器（`evaluation.py`）まで。判定は人間 |
| 2 | `bridge.py` + `state.py` | 基準1 ✅ |
| 3 | `meta_speech.py` + `composers.py`(Prosody) | 基準5 ✅ |
| 4 | `expression.py`（アセットはプレースホルダ運用） | 基準6 ✅ |
| 5 | `memory.py` | — |
| 6 | `registry.py` + `presets.py` + REST 管理I/F | 基準2は計測関数まで |
| 7 | `room/`（N=1 運用） | 基準10 ✅ |
| 8 | `porter.py` | 基準7 ✅ |
| 9 | `breeder.py` | 基準8・9 ✅ |
| 10 | `room/arbiter.py` + 複数体同時稼働 + 人間司会 | 基準11・12 ✅ |

「現在の人格」というグローバル状態は存在しない（§2.6）。Phase 7 の1体運用と
Phase 10 の複数体は同じ `Room.enter/leave` のみで表現され、切り替え専用コードはない。

## 仕様が実装に委ねた点の判断

1. **メタ発話のプリベイク器**（§7.2「生成は LLM で行ってよい」）
   既定は LLM を使わない `RuleBasedBaker` とした。素材テーブル
   （`tables/meta_templates.yaml`）から distance に応じたレジスタ（敬体/常体）を選び、
   verbalTics を長さの許す範囲で織り込む。人格の決定的な関数であり、オフラインで
   全テストが回る。LLM ベイカーは `TemplateBaker` プロトコルに差し込める

2. **「読み上げ1.5秒」の文字数換算**(§7.3)
   日本語 TTS の標準速度を約9文字/秒と置き、filler / backchannel は **13文字以内**
   とした（`meta_speech.MAX_SHORT_CHARS`）。ベイク時に超過分を除外する

3. **テンプレート選択の「擬似ランダム」**（§7.2）
   選択は乱数ではなく**決定的ローテーション**（開始位置は persona.id の CRC32）にした。
   「連続で同じものを選ばない（直近2件除外）」を満たしつつ、同一プロセス列で
   再現可能になり、デバッグと基準10の検証が容易になる。乱数を使っても仕様violated
   ではないが、使わずに済むなら §2.5 の精神により近い

4. **bid 条件の解釈**（§11.6）
   仕様の bid 条件は AI 同士のやり取りを主に想定した記述のため、次のとおり補った:
   - **人間の発話には常に bid する**（誰かが応えるべき。誰が先かは backoff が決める）
   - 他 AI の発話には「名指し」か「expertise 一致」のときのみ bid（仕様通り）
   - 名指し（高優先 bid）の backoff は **initiative 非依存の 50ms 基準**とした。
     initiative の係数倍にすると、低主導の人格が名指しされても高主導の人格に
     先を越され「名指しの意図」が壊れるため。50ms + jitter(≤120ms) < 通常最短 200ms
     が常に成り立ち、名指しされた人格が必ず先に発話権を取る
   - 「直近 N ターン沈黙」ブーストは backoff の短縮（×0.75）として実装

5. **ターン上限の安全弁の置き場所**（§11.7）
   `Room` が task 発話を数え、上限超過で `turn_limit` イベントを**配信**する。
   これを受けた各インスタンスがローカルに bid を停止し、人間の発話で再開する。
   Room は「誰が喋るか」を決めておらず（§11.4）、停止判断は各インスタンスに残る

6. **正常応答時の handoff**（§7.1「Agent 応答の受信直前」）
   受信の「直前」は観測できないため、**progress を出した長時間処理に限り**、
   受信直後・回答発話前に handoff を出す。全応答に付けると短い応答で冗長になる

7. **タスク成功イベント**（§6.1）
   Agent が正常応答を返した時点を「タスク成功」（arousal +0.25、表情 pleased）と
   解釈した。業務的な成否は Agent 側の関心事であり、人格レイヤーからは応答の
   成立/失敗（エラー）だけが観測できる

8. **訂正の検出**（§9.1）
   軽量分類器はルールベースで実装（「違うよ」「間違って」「訂正」等のマーカー）。
   選好表明・明示依頼も正規表現で判定する。LLM 分類器に差し替える場合も
   `memory.classify_utterance` の置き換えだけで済む

9. **lineage の親が居ない環境へのインポート**（§10/§12.5）
   移植先に親人格が存在しない場合、参照切れの系譜を持ち込まず lineage を外して
   受け入れる。移植先の家系図の整合性を優先した

10. **編集での lineage 改変禁止**
    `PersonaRegistry.update` は lineage の変更を拒否する。系譜は Breed だけが
    書ける事実であり、編集で書き換えられると家系図の信頼性がなくなる

11. **サーバ / ブラウザコンソールの位置づけ**（§1.3）
    会議UI（WebRTC・画面共有・音声入出力）は別コンポーネントのため、
    `server.py` は外部UIが接続するリファレンス I/F（REST + WebSocket のイベント
    ストリーム）に留めた。`web/index.html` は動作確認用の簡易コンソールであり、
    SSML prosody を Web Speech API に写像して読み上げの雰囲気だけ確認できる

12. **スプライトアセット**（§8.2）
    画像アセットは本リポジトリに含めない（18枚の WebP は制作物）。
    `ExpressionMachine` は表情IDを出力し、`porter` は sprites/ ディレクトリが
    与えられればパッケージに同梱する。表情IDとコマ数・fps の契約は
    `tables/expressions.yaml` に記載

## 既存 AI Agent への接続（agent.py / config.py）

仕様書は「タスク回答の生成はすべて Agent 側の責務」（§1.3）とし、人格レイヤーは
その回答を素通しする（§2.1）。したがって**本来の接続先は既存の AI Agent** であり、
LLM 直結は配線確認用の位置づけである。

- **接続の継ぎ目は `Agent` プロトコル**（`respond(system, prompt) -> str`）。
  `AgentBridge` はこれ越しにしか外部と喋らず、1 PersonaInstance = 1 Agent（§11.1）。
- 既存 Agent 接続用に3方式を同梱した。いずれも**設定ファイルだけで繋がる**ことを重視:
  - `HTTPAgent`: 任意の JSON API。**送信フィールド名（`send:`）と回答の取り出し位置
    （`receive:`、ドット記法）を設定で寄せられる**のが要点。既存 Agent 側を改修せずに
    済ませるため。`null` 指定でそのフィールドを送らないこともできる
  - `OpenAICompatibleAgent`: `/chat/completions` 互換を出している Agent 用（LLM と共用）
  - `load_python_agent`: `module:Class` で同一プロセスの Python 実装を読む
- **Agent プロトコルの拡張は後方互換**とした。必須は従来どおり `respond(system, prompt)`
  のままで、会話の役割構造やセッションIDを活かしたい Agent だけが任意メソッド
  `respond_request(AgentRequest)` を実装する。`AgentBridge.ask()` は `hasattr` で
  前者/後者を選ぶ。`ask()` は文字列も受け付ける（既存呼び出し・テストの互換維持）
- `AgentRequest` には `system`（人格記述）に加え、**構造化した `persona`**
  （6軸・一人称・expertise）と `session_id` を載せた。system プロンプトを解釈しない
  Agent や、自前で履歴を持つ Agent でも人格情報を使えるようにするため
- 設定の `agents:` が provider 推定より**優先**される解決順にした
  （`agents.<id>` → agentId プレフィックス推定 → 既定 provider → キー無しなら Echo）
- `bindings:` で人格 → Agent の割り当てと `expertise` を設定できるようにした。
  `expertise` は §11.6 の bid 判定と §11.2 の他人格提案にそのまま効く。
  ブラウザからの入室は `agentId` 省略時に登録済み Binding を参照する
- ヘッダ等に `${ENV_VAR}` を書けるようにし（`config.expand_env`）、
  API キーを設定ファイルに直書きしないで済むようにした

### 応答文脈の構造化（品質改善）

従来は会話履歴を1本の平文に潰して単一 user メッセージで渡していた。これを
`AgentTurn`（role / 話者名 / `is_self`）のリストに変更し、LLM アダプタは
user/assistant の多ターンとして送るようにした（Gemini は user/model へ写像）。

- Anthropic / Gemini は role の交互を要求するため、連続する同 role を結合し、
  先頭の assistant は落とす（`_merge_consecutive`）
- 自分以外の発話には話者名を前置して「誰の主張か」を保つ（§11.5）
- 平文 `prompt` も引き続き組み立てて `AgentRequest.prompt` に載せ、
  `respond_request` 非対応の Agent へのフォールバックにしている
- 依頼文（`instruction`）は「具体的に述べる／相槌だけで終わらせない」を明示。
  相槌はメタ発話が担うため、回答側での重複を防ぐ。回答の**内容**は指示していない（§2.1）
- 既定 `max_tokens` を 1024 → 2048 に引き上げた（思考トークンが出力上限に含まれる
  モデルで応答が途中で切れるのを避けるため）

## LLM プロバイダの選択（config.py / agent.py）

仕様書は Agent の実体（どの LLM か）を人格レイヤーの範囲外（§1.3）としているため、
接続先はプラガブルにし、設定ファイルで選べるようにした。

- 対応プロバイダ: **OpenRouter / Gemini / Anthropic / OpenAI**。
  OpenRouter は OpenAI 互換 API のため `OpenAICompatibleAgent` を OpenAI 本家と
  共用し、差分（base_url・キー・任意ヘッダ）だけ設定で与える。Gemini は
  `systemInstruction` + `contents` 形式の専用アダプタ
- **API キーは設定ファイルに書かず環境変数から読む**（鍵をリポジトリにコミット
  しないため）。`persona-layer.config.yaml` は `.gitignore` 済み。設定側で
  `api_key_env` を指定すれば別名の環境変数も使える
- キー未設定のプロバイダを指したときは、デモが止まらないよう `EchoAgent` に
  フォールバックする（`build_agent`）。`persona-layer config` で有効な設定を確認できる
- `provider: auto`（設定ファイル無しの既定）は、キーのある環境変数を検出して
  プロバイダを自動選択する。既存の `make_agent` は `build_agent` の薄い別名にして
  後方互換を保った
- ネットワークに出さずに検証できるよう、各アダプタは httpx の `transport` を
  差し込めるようにし、テストは `httpx.MockTransport` でリクエスト/レスポンス形式を
  検証している（実キー不要）

## 非機能要件の担保（§14）

- 実行時の追加 LLM 呼び出し 0回: メタ発話=プリベイク済みキャッシュ選択、
  表情・prosody=静的テーブル参照のみ（テストで 1000回選択 <100ms を確認）
- タスク回答の追加遅延 0ms: `AgentBridge` は受信テキストをそのまま publish する
- 発話権の衝突: backoff 差（initiative 1段で 200〜300ms）+ jitter(0〜120ms) で分離。
  同 initiative 同士は jitter のみで割れるため理論上稀に競るが、
  carrier sense の再確認（§11.6 手順5）で二重発話は起きない
- manifest < 4KB: `porter` がエクスポート時に検査して超過を拒否する

## 既知の制限・将来課題

- 基準2・3・4 の「実測」は LLM/人間参加が必要（素材と計測器のみ同梱）
- STT・実 TTS 接続は会議UI側の責務。`TTSAdapter`（stop() 付き・§7.3）だけ定義済み
- `reporting` context への遷移トリガー（画面共有開始の検知）は会議UIからの
  明示通知を想定（`StateEngine.set_context("reporting")`）
- 無人議論用の司会人格は未実装（§11.8 の v1 スコープ外。通常人格1体で後付け可）
