@echo off
rem 未処理ぶんを1回だけ書き出す（動作確認用）。
setlocal
cd /d "%~dp0.."
python -m withper_exporter run %*
endlocal
