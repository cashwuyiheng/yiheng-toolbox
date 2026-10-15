@echo off
chcp 936 >nul
title XiaoHua Monitor

set PY=pythonw.exe
set SCRIPT=.\微信监控\脚本\wechat_monitor.py
set LOG=.\微信监控\数据\monitor.log

echo.
echo [1/2] Killing old monitor processes...
taskkill /f /im pythonw.exe >nul 2>&1
timeout /t 2 >nul

echo [2/2] Starting monitor...
start "" "%PY%" "%SCRIPT%" --loop 300 --log "%LOG%"
timeout /t 12 >nul

tasklist /fi "imagename eq pythonw.exe" | find /i "pythonw.exe" >nul
if errorlevel 1 (
    echo [FAIL] Monitor did not start.
) else (
    echo [OK] Monitor is running.
)

echo.
echo Adding auto-restart task...
schtasks /create /tn "XiaoHuaWeChatMonitor" /tr "\"pythonw.exe\" \".\微信监控\脚本\wechat_monitor.py\" --loop 300 --log \".\微信监控\数据\monitor.log\"" /sc minute /mo 5 /f >nul 2>&1
if errorlevel 1 (
    echo [WARN] Could not add 5-min watchdog task.
    echo        Try right-click - Run as administrator.
) else (
    echo [OK] Watchdog added: checks every 5 minutes.
)

echo Adding startup task...
schtasks /create /tn "XiaoHuaWeChatMonitorBoot" /tr "\"pythonw.exe\" \".\微信监控\脚本\wechat_monitor.py\" --loop 300 --log \".\微信监控\数据\monitor.log\"" /sc onlogon /f >nul 2>&1
if errorlevel 1 (
    echo [WARN] Could not add startup task.
) else (
    echo [OK] Startup task added.
)

echo.
echo Done. You can close this window.
pause
