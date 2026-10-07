@echo off
rem ------------------------------------------------------------------
rem  ساخت نسخه‌ی ویندوزی (exe) روی همین سیستم — بدون پنجره‌ی CMD
rem  خروجی: dist\PSD-Batch-Generator\PSD-Batch-Generator.exe
rem
rem  برای ساخت تک‌فایلی:  set PSD_BATCH_ONEFILE=1  (قبل از اجرا)
rem ------------------------------------------------------------------
cd /d "%~dp0.."
where python >nul 2>nul
if errorlevel 1 (
  echo Python not found. Install it from python.org and tick "Add python.exe to PATH".
  pause
  exit /b 1
)
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pip install pyinstaller
python -m PyInstaller packaging\windows.spec --noconfirm --clean
echo.
echo تمام شد. فایل اجرایی:
echo   %CD%\dist\PSD-Batch-Generator\PSD-Batch-Generator.exe
pause
