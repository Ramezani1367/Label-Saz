@echo off
rem ------------------------------------------------------------------
rem  اجرای برنامه روی ویندوز «بدون پنجره‌ی CMD»
rem  (اگر پایتون نصب باشد کافی است؛ این پنجره بلافاصله بسته می‌شود)
rem ------------------------------------------------------------------
cd /d "%~dp0"
where pythonw >nul 2>nul
if errorlevel 1 (
  echo Python not found. Install it from python.org and tick "Add python.exe to PATH".
  echo https://www.python.org/downloads/
  pause
  exit /b 1
)
start "" pythonw "%~dp0windows_app.pyw"
exit /b 0
