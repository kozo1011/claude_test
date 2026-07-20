#!/usr/bin/env bash
# ============================================================
#  Persona Layer かんたん起動スクリプト（Mac / Linux 用）
#  ターミナルで  ./run.sh  と実行すると、必要な準備を自動で行い、
#  ブラウザで人格レイヤーのデモ画面を開きます。
# ============================================================
set -e
cd "$(dirname "$0")"

echo
echo "  Persona Layer を起動します..."
echo

# --- Python があるか確認 ---
if ! command -v python3 >/dev/null 2>&1; then
  echo "[エラー] python3 が見つかりませんでした。"
  echo "  https://www.python.org/downloads/ から Python をインストールしてください。"
  exit 1
fi

# --- 仮想環境を作成（初回のみ） ---
if [ ! -d ".venv" ]; then
  echo "  初回セットアップ中です。1〜2分ほどお待ちください..."
  python3 -m venv .venv
fi

# --- 必要な部品をインストール ---
# shellcheck disable=SC1091
source .venv/bin/activate
python -m pip install --quiet --upgrade pip
python -m pip install --quiet -e .

# --- 3秒後にブラウザを自動で開く（サーバの起動を待つため） ---
( sleep 3
  if command -v open >/dev/null 2>&1; then open http://127.0.0.1:8000/
  elif command -v xdg-open >/dev/null 2>&1; then xdg-open http://127.0.0.1:8000/
  fi ) &

echo
echo "  準備ができました。ブラウザで http://127.0.0.1:8000/ を開きます。"
echo "  ★ 使い方: 画面上部で人格を選び「入室」→ 下の欄にメッセージを入力"
echo "  ★ 終了するには、このターミナルで Ctrl+C を押してください"
echo

python -m persona_layer.cli serve \
  personas/sewa-yaku-kaede.json \
  personas/shokunin-gen.json \
  personas/kenja-shion.json
