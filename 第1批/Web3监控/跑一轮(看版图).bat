@echo off
chcp 65001 >nul
cd /d "%~dp0"
python "%~dp0web3监控.py" --open
echo.
pause
