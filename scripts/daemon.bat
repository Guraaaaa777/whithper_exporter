@echo off
rem 常駐モードで起動する。閉じると止まるので、常用はタスクスケジューラ方式を推奨。
setlocal
cd /d "%~dp0.."
python -m withper_exporter daemon --flush-on-exit %*
endlocal
