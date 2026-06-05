@echo off
setlocal
cd /d "%~dp0"
echo PCライフログ統計ダッシュボードを起動しています...
echo ブラウザが開かない場合は http://127.0.0.1:8765 を開いてください。
python app.py
pause
