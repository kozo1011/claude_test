@echo off
chcp 65001 >nul
REM ============================================================
REM  Persona Layer かんたん起動スクリプト（Windows 用）
REM  このファイルをダブルクリックすると、必要な準備を自動で行い、
REM  ブラウザで人格レイヤーのデモ画面を開きます。
REM ============================================================
cd /d "%~dp0"

echo.
echo   Persona Layer を起動します...
echo.

REM --- Python があるか確認 ---
py --version >nul 2>&1
if errorlevel 1 (
  echo [エラー] Python が見つかりませんでした。
  echo.
  echo   https://www.python.org/downloads/ を開き、Python をインストールしてください。
  echo   インストール画面の最初に出る「Add Python to PATH」に必ずチェックを入れてください。
  echo   インストール後、このファイルをもう一度ダブルクリックしてください。
  echo.
  pause
  exit /b 1
)

REM --- 仮想環境を作成（初回のみ・少し時間がかかります） ---
if not exist ".venv" (
  echo   初回セットアップ中です。1〜2分ほどお待ちください...
  py -m venv .venv
)

REM --- 必要な部品をインストール ---
call ".venv\Scripts\activate.bat"
python -m pip install --quiet --upgrade pip
python -m pip install --quiet -e .
if errorlevel 1 (
  echo [エラー] セットアップに失敗しました。ネット接続を確認して、もう一度お試しください。
  pause
  exit /b 1
)

REM --- 3秒後にブラウザを自動で開く（サーバの起動を待つため） ---
start "" cmd /c "timeout /t 3 >nul & start http://127.0.0.1:8000/"

echo.
echo   準備ができました。ブラウザで下の画面が開きます:
echo       http://127.0.0.1:8000/
echo.
echo   （もし画面がすぐ開かない・エラーになる場合は、数秒待って
echo     ブラウザの再読み込みボタンを押してください）
echo.
echo   ★ 使い方: 画面上部で人格を選び「入室」→ 下の欄にメッセージを入力
echo   ★ 終了するには、この黒い画面で Ctrl+C を押すか、この画面を閉じてください
echo.

python -m persona_layer.cli serve personas\sewa-yaku-kaede.json personas\shokunin-gen.json personas\kenja-shion.json

pause
