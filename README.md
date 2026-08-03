# Persona Layer

AI Agent と人間のリアルタイム対話において、Agent に**キャラクター性を与える中間レイヤー**。
[開発指示書 v0.4](docs/persona-layer-spec.md) に準拠した実装です。

- タスク回答は**素通し**（内容の書き換えなし・§2.1）。人格が乗るのは回答の前後の
  メタ発話と、声（SSML prosody）・表情のみ
- 実行時の追加 LLM 呼び出しは **0回**（メタ発話はプリベイク、表情・prosody は
  静的テーブルの決定的マッピング・§2.2/§2.3）
- 人格は「6軸の整数 + 文字列数個 ≒ 1KB の JSON」。`.persona` パッケージで
  **他の Agent へ移植**でき、**交配（Breed）**で新人格を生成できる
- 実行時モデルは **Room + PersonaInstance**（§2.6）。1体運用は N=1 のルームで、
  複数体の AI 議論（発話権は CSMA/CD 型の分散調停・§11.6）と同じ仕組み

## いちばん簡単な試し方（Windows・専門知識不要）

コマンドの知識がなくても、次の手順でブラウザ上のデモを動かせます。

1. **Python を入れる**（初回だけ）
   [python.org/downloads](https://www.python.org/downloads/) を開き、ダウンロードした
   インストーラを実行します。最初の画面の下にある **「Add Python to PATH」に必ず
   チェック**を入れてから「Install Now」を押してください。
2. **このプロジェクトをダウンロードする**
   GitHub のこのリポジトリのページで、緑色の **「Code」ボタン → 「Download ZIP」** を
   押します。ダウンロードした ZIP を右クリック →「すべて展開」でフォルダにします。
3. **`run.bat` をダブルクリックする**
   展開したフォルダの中にある **`run.bat`** をダブルクリックします。初回だけ準備に
   1〜2分かかり、その後ブラウザで操作画面が自動的に開きます
   （開かなければ、少し待って再読み込みしてください）。
4. **画面で遊ぶ**
   画面上部で人格（楓・源・紫苑）を選び **「入室」** を押し、下の欄にメッセージを
   入力して送信します。相槌・つなぎ言葉（メタ発話）や表情・声のパラメータが
   人格ごとに変わる様子を確認できます。
   終了するときは、いっしょに開いた黒い画面（コマンド画面）を閉じてください。

> Mac の場合は、ターミナルでフォルダに移動して `./run.sh` を実行してください。

### うまく動かないとき（手動で起動する）

`run.bat` が OS（Windows の SmartScreen）にブロックされる場合や、ブラウザに
**「接続が拒否されました」** と出る場合は、次の手順で手動起動できます。
「接続が拒否されました」は、**サーバー本体がまだ起動していない**ときに出ます。

1. 展開したフォルダをエクスプローラーで開き、**アドレスバーに `cmd` と入力して Enter**
   （そのフォルダでコマンドプロンプトが開きます）
2. **準備（初回だけ）**:
   ```
   py -m venv .venv
   .venv\Scripts\python -m pip install -e .
   ```
3. **サーバーを起動（毎回・この1行）**:
   ```
   .venv\Scripts\python -m persona_layer.cli serve personas\sewa-yaku-kaede.json personas\shokunin-gen.json personas\kenja-shion.json
   ```
   → `Uvicorn running on http://127.0.0.1:8000` と出て**止まったように見えれば正常**
   （サーバーが動作中）。この黒い画面は**閉じないでください**。
4. その表示が出てから、ブラウザで **http://127.0.0.1:8000/** を開きます。
5. 終了するときは、この黒い画面で `Ctrl + C` を押すか画面を閉じます。

> `run.bat` のブロックを解除するには、`run.bat` を右クリック →「プロパティ」→
> 下部の **「許可する(Unblock)」にチェック → OK**。

**「回答の中身」について**: この状態では、接続先の AI（Agent）はダミーで、送った言葉を
オウム返しします。これは**わざと**です。この人格レイヤーは仕様上、**回答の中身は作らず**
（それは Agent の仕事）、その**前後の相槌・声・表情だけ**を担当します。本物の AI 回答を
見たい場合は、Agent に API キーをつなぎます（下記「本物の AI につなぐ」参照）。

## セットアップ（開発者向け）

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest   # 受け入れ基準 1,5,6,7,8,9,10,11,12 の自動テストを含む83件
```

### 既存の AI Agent につなぐ（本来の使い方）

人格レイヤーは**回答の中身を作りません**（仕様書 §1.3）。タスクを解くのは接続先の
Agent の役割で、本レイヤーはその回答を**書き換えずに素通し**し（§2.1）、
前後の相槌・声・表情・発話タイミングだけを担当します。
自作の AI Agent（HermesAgent など）は**コードを書かずに設定ファイルだけ**で接続できます。

`persona-layer.config.yaml` に接続先を書きます。

```yaml
agents:
  hermes:
    type: http
    url: http://localhost:9000/chat
    headers:
      Authorization: "Bearer ${HERMES_API_KEY}"   # ${} は環境変数に展開
    receive: content        # 回答の取り出し先（"result.reply" のような入れ子も可）

bindings:                   # 人格ごとに接続先と得意分野を割り当てる（§4.3）
  - persona: sewa-yaku-kaede
    agent: hermes
    expertise: [売上, 経費精算]
```

これだけで、人格レイヤーは次の JSON を Agent へ POST します。

```json
{
  "system": "あなたは「楓」として振る舞います。…（人格の指示文）",
  "messages": [{"role": "user", "content": "…", "speakerName": "利用者",
                "speakerKind": "human", "isSelf": false}],
  "text": "直前の相手の発話",
  "instruction": "今回の依頼文",
  "persona": {"id": "…", "displayName": "楓", "style": {"distance": 2, …},
              "expertise": ["売上"]},
  "sessionId": "sewa-yaku-kaede@hermes:default"
}
```

Agent 側は `{"content": "回答テキスト"}` を返すだけです。
**送受信のフィールド名は `send:` / `receive:` で自由に変更できる**ので、
既存 API を改修せずそのまま繋げます（使わない項目は `null` を指定すれば送りません）。

| 接続方式 | `type` | 使う場面 |
|---|---|---|
| HTTP JSON API | `http` | もっとも汎用。既存 Agent の API 形状に合わせられる |
| OpenAI 互換 API | `openai_compatible` | Agent が `/chat/completions` 互換を出している場合 |
| Python 直接 | `python` | Agent が Python 製で、同一プロセスで動かす場合（`target: "module:Class"`） |
| LLM 直結 | `llm` | 人格ごとに別 LLM を割り当てたい場合 |

```bash
persona-layer config                                  # 接続先の確認
persona-layer serve personas/*.json                   # ブラウザで対話
persona-layer demo personas/sewa-yaku-kaede.json -a hermes   # ターミナルで対話
```

接続先が落ちている場合は `apology` のメタ発話（「すみません、失敗しました」）に
自動で切り替わり、ルームは動き続けます。

### LLM に直結する（配線確認・単体デモ用）

接続先の Agent を用意せず、LLM に直接喋らせることもできます。
対応プロバイダは **OpenRouter / Gemini / Anthropic / OpenAI**。使うプロバイダと
モデルは**設定ファイル**で選び、**API キーは環境変数**で渡します。

> **注意**: この構成は配線確認・単体デモ向けです。素の LLM に会話文脈を渡すだけで、
> タスクを解く仕組み（ツール・知識・記憶）が無いため、応答は一般的な雑談の域を出ません。
> 実用的な応答が必要な場合は、上記「既存の AI Agent につなぐ」を使ってください。

**手順:**

1. サンプルをコピーして設定ファイルを作る
   ```bash
   cp persona-layer.config.example.yaml persona-layer.config.yaml
   ```
2. `persona-layer.config.yaml` を編集し、`provider:` に使いたいものを書く
   （`openrouter` / `gemini` / `anthropic` / `openai`）。モデル名も同ファイルで指定。
3. API キーを環境変数に設定する（キーは設定ファイルには書きません）

| プロバイダ | 環境変数 | モデル指定の例 |
|---|---|---|
| OpenRouter | `OPENROUTER_API_KEY` | `openai/gpt-4o-mini`, `anthropic/claude-3.5-sonnet` 他 |
| Gemini | `GEMINI_API_KEY`（`GOOGLE_API_KEY` 可） | `gemini-2.0-flash`, `gemini-2.5-flash` 他 |
| Anthropic | `ANTHROPIC_API_KEY` | `claude-sonnet-5` 他 |
| OpenAI | `OPENAI_API_KEY` | `gpt-4o-mini` 他 |

```bash
# 例: OpenRouter を使う（Mac / Linux）
export OPENROUTER_API_KEY=（あなたのキー）
python -m persona_layer.cli config     # 有効な設定を確認
python -m persona_layer.cli demo personas/sewa-yaku-kaede.json   # ターミナルで対話
python -m persona_layer.cli serve personas/*.json               # ブラウザで対話

# Windows（コマンドプロンプト）は set を使います
set OPENROUTER_API_KEY=（あなたのキー）
```

`run.bat` / `run.sh` を使う場合も、フォルダ内に `persona-layer.config.yaml` を
置いて対応する環境変数を設定しておけば、ブラウザ版がそのプロバイダで動きます
（キーが無ければ自動でダミーに戻るので、設定ミスでも起動は止まりません）。

- **設定ファイルの場所**: カレントディレクトリの `persona-layer.config.yaml`、
  または環境変数 `PERSONA_LAYER_CONFIG`、または `--config パス` で指定
- **`provider: auto`**（設定ファイルが無いときの既定）: 環境変数にキーがある
  プロバイダを自動で選びます（複数あれば anthropic → openai → openrouter → gemini の順）

## CLI クイックスタート

```bash
# プリセット（§13）から人格を作成
persona-layer presets
persona-layer create --preset 世話役 --id kaede --name 楓 -o kaede.json
persona-layer show kaede.json
persona-layer prompt kaede.json          # PromptComposer の出力（Agent へ注入する人格記述）

# 交配（§12）: 同じ親 × 同じ seed は常に同じ子
persona-layer breed personas/sewa-yaku-kaede.json personas/shokunin-gen.json --seed 42 -o child.json

# 移植（§10）: .persona パッケージ（manifest.json + voice.json + sprites/）
persona-layer export kaede.json
persona-layer import kaede.persona

# デモルーム（複数ファイルを渡すと複数体の同時稼働）
persona-layer demo personas/sewa-yaku-kaede.json personas/shokunin-gen.json

# リファレンスAPIサーバ + ブラウザコンソール（http://127.0.0.1:8000/）
persona-layer serve personas/*.json
```

`ANTHROPIC_API_KEY` を設定すると Agent が LLM（`AnthropicAgent`）になり、
未設定ならモック（`EchoAgent`）で配線確認ができます。

## リポジトリ構成

| パス | 内容 | 仕様書 |
|---|---|---|
| `src/persona_layer/models.py` | Persona / PersonaBinding / PersonaState / MemoryRecord（3分割） | §4 |
| `src/persona_layer/tables/*.yaml` | §5.1 文言表・§5.3 prosody・§8.1 表情・§11.6 調停（テーブル駆動） | §5, §8, §11 |
| `src/persona_layer/composers.py` | PromptComposer / ProsodyComposer（純関数） | §5 |
| `src/persona_layer/state.py` | StateEngine（arousal / familiarity / context） | §6 |
| `src/persona_layer/meta_speech.py` | メタ発話のプリベイクと選択 | §7 |
| `src/persona_layer/expression.py` | ExpressionMachine（決定的マッピング） | §8 |
| `src/persona_layer/memory.py` | PersonaMemory（機械的トリガー・責務分離） | §9 |
| `src/persona_layer/agent.py` | Agent 抽象と接続アダプタ（HTTP / Python / OpenAI互換 / Anthropic / Gemini / Echo） | §1.3 |
| `src/persona_layer/config.py` | 接続先 Agent・LLM プロバイダ・人格割り当ての設定（YAML + 環境変数） | §1.3, §4.3 |
| `persona-layer.config.example.yaml` | 設定ファイルのサンプル（コピーして使う） | — |
| `src/persona_layer/bridge.py` | AgentBridge（素通し保証・1:1） | §2.1, §11.1 |
| `src/persona_layer/room/` | Room / RoomBus / PersonaInstance / SpeechArbiter | §3, §11 |
| `src/persona_layer/porter.py` | PersonaPorter（`.persona` パッケージ） | §10 |
| `src/persona_layer/breeder.py` | PersonaBreeder（一様交叉 + 突然変異） | §12 |
| `src/persona_layer/presets.py` | 賢者・道化・世話役・職人・探究者 | §13 |
| `src/persona_layer/registry.py` | PersonaRegistry（版管理・tombstone・逆引き系譜） | §11.1, §12.5 |
| `src/persona_layer/evaluation.py` | 軸スイープ生成・一貫性計測（基準2・3・4の素材） | §15 |
| `src/persona_layer/server.py` + `web/` | 外部会議UI向けのリファレンスI/F + 簡易コンソール | §1.3 |
| `personas/` | サンプル人格（プリセット由来） | — |
| `docs/persona-layer-spec.md` | 開発指示書 v0.4（原文） | — |
| `docs/implementation-notes.md` | 実装ノート（仕様が実装に委ねた点の判断記録） | — |

## 受け入れ基準の状況（§15)

| # | 基準 | 状況 |
|---|---|---|
| 1 | 素通しの保証 | ✅ 自動テスト |
| 2 | 同一性の一貫性 | ⚙ 計測関数を提供（LLM対話が必要なため実測は運用時） |
| 3・4 | 軸の有効性・直交性 | ⚙ 盲検素材の生成器を提供（人間の判定が必要） |
| 5 | メタ発話の先行 | ✅ 自動テスト |
| 6 | 表情の決定性 | ✅ 自動テスト |
| 7 | 移植の同一性 | ✅ 自動テスト |
| 8 | Breed の再現性 | ✅ 自動テスト |
| 9 | Breed の多様性 | ✅ 自動テスト（50体・分散比較） |
| 10 | 実行時の決定性 | ✅ 自動テスト |
| 11 | 自己反応の非発生 | ✅ 自動テスト |
| 12 | 発話権の秩序 | ✅ 自動テスト |
