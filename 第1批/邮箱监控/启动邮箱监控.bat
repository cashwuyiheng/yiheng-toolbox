@echo off
chcp 936 >nul
title XiaoHua Mail Monitor

REM 注意：这里故意不 taskkill pythonw.exe，否则会把微信监控一起杀掉。

set PY=pythonw.exe
set SCRIPT=.\邮箱监控\脚本\邮箱监控.py
set LOG=.\邮箱监控\数据\monitor.log

echo.
echo [1/2] Starting mail monitor...
start "" "%PY%" "%SCRIPT%" --loop 300 --log "%LOG%"
timeout /t 12 >nul

tasklist /fi "imagename eq pythonw.exe" | find /i "pythonw.exe" >nul
if errorlevel 1 (
    echo [FAIL] Monitor did not start.
) else (
    echo [OK] Monitor is running.
)

echo.
echo Adding startup task (runs on logon)...
schtasks /create /tn "XiaoHuaMailMonitorBoot" /tr "\"pythonw.exe\" \".\邮箱监控\脚本\邮箱监控.py\" --loop 300 --log \".\邮箱监控\数据\monitor.log\"" /sc onlogon /f >nul 2>&1
if errorlevel 1 (
    echo [WARN] Could not add startup task. Try "Run as administrator".
) else (
    echo [OK] Startup task added.
)

echo.
echo Done. You can close this window.
pause
