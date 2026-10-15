@echo off
cd /d "%~dp0"
echo ================================================
echo   WeChat DB key extraction (READ-ONLY scan)
echo   It only reads memory. Nothing is modified.
echo ================================================
echo.
python wcdb_key_tool_windows.py extract --db-dir "C:\Users\<你>\OneDrive\xwechat_files\wxid_YOUR_ACCOUNT_9e8a\db_storage" --output "%~dp0all_keys.json"
echo.
echo ================================================
echo   Done. Screenshot the output above.
echo ================================================
pause
