@echo off
rem 启动本地 AI 网关（免费额度池）。双击即可；关掉窗口不影响，它是后台窗口。
cd /d "%~dp0"
start "" "pythonw.exe" "%~dp0ai_relay.py"
