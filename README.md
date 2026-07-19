# Persona Layer

AI エージェントと人間のあいだに立つ、**移植可能な人格（ペルソナ）インターフェース層**。

- 人格を YAML/JSON の定義ファイル（PPD: Portable Persona Definition）として管理
- チャット（CLI / Web / REST / WebSocket）と音声（ブラウザ STT/TTS、VOICEVOX 対応）の両チャネル
- 応答の中身は LLM でも「上流の別エージェント」でもよい —— eラーニングでは
  教材エージェントが内容を決め、本レイヤーが講師人格として話す
- 作成した人格は `persona export` で **任意の他の AI エージェントへ移植可能**

詳細仕様は [docs/persona-layer-spec.md](docs/persona-layer-spec.md) を参照。

## セットアップ

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

## クイックスタート

```bash
# ペルソナ定義の検証・確認
persona validate personas/tutor_haru.yaml
persona show personas/tutor_haru.yaml

# ターミナルで会話（APIキー未設定ならモック応答）
export ANTHROPIC_API_KEY=...   # または OPENAI_API_KEY
persona chat personas/tutor_haru.yaml

# Web + 音声チャネル（http://127.0.0.1:8000/ をブラウザで開く）
persona serve
```

ブラウザクライアントでは 🎤 で音声入力、🔊 で読み上げの ON/OFF ができます
（Web Speech API 対応ブラウザ。Chrome / Edge 推奨）。

## 人格を他のエージェントへ移植する

```bash
persona export personas/tutor_haru.yaml -f system-prompt   # 任意のLLMの指示欄へ
persona export personas/tutor_haru.yaml -f markdown        # GPTs / Dify 等へ貼り付け
persona export personas/tutor_haru.yaml -f anthropic       # Anthropic API リクエスト雛形
persona export personas/tutor_haru.yaml -f openai          # OpenAI API リクエスト雛形
persona export personas/tutor_haru.yaml -f json            # 正規形式（実装間交換用）
```

## eラーニング（教材エージェント中継）構成

```bash
export PERSONA_BACKEND=relay
export RELAY_URL=http://localhost:9000/lesson-agent   # 教材エージェントのURL
export ANTHROPIC_API_KEY=...                          # 講師人格への文体変換用
persona serve
```

上流エージェントは `POST $RELAY_URL` に対して
`{"content": "<応答テキスト>"}` を返すだけでよい（契約の詳細は仕様書 §6）。

## 主な環境変数

| 変数 | 説明 |
| --- | --- |
| `PERSONA_BACKEND` | `auto`（既定）/ `mock` / `anthropic` / `openai` / `relay` |
| `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` | LLM バックエンド用 |
| `PERSONA_MODEL` | 使用モデルの上書き |
| `RELAY_URL` | 中継モードの上流エージェント URL |
| `VOICEVOX_URL` | 設定するとサーバサイド TTS（VOICEVOX）が有効化 |

## テスト

```bash
pytest
```
