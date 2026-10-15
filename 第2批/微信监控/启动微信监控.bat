@echo off
rem ================================================
rem  WeChat monitor launcher
rem  Auto-start on logon (registered in Task Scheduler)
rem  Log: 数据\monitor.log
rem ================================================
cd /d "%~dp0"

rem Make sure the log folder exists
if not exist "数据" mkdir "数据"

rem Run in background: no console window, output goes to the log file
start "" /min pythonw wechat_monitor.py --loop 300 --log "数据\monitor.log"
