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

### 本物の AI につなぐ（任意）

Anthropic の API キーがあれば、ダミーの代わりに実際の LLM が回答を生成します
（人格レイヤーはその回答を書き換えず、声・表情・相槌だけを乗せます）。ターミナルの
`demo` コマンドは、キーが設定されていれば自動で LLM Agent を使います。

```bash
# Windows（コマンドプロンプト）:
set ANTHROPIC_API_KEY=（あなたのキー）
python -m persona_layer.cli demo personas\sewa-yaku-kaede.json

# Mac / Linux:
export ANTHROPIC_API_KEY=（あなたのキー）
python -m persona_layer.cli demo personas/sewa-yaku-kaede.json
```

（ブラウザ版 `serve` はオフラインでも確実に動くよう、接続先を常にダミー Agent に
固定しています。実 LLM を組み込むときは `AgentPool`／画面の `agentId` を差し替えます。）

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
