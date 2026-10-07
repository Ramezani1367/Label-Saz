@echo off
chcp 65001 >nul
title تولید انبوه تصویر از قالب فتوشاپ
cd /d "%~dp0"
where python >nul 2>nul
if errorlevel 1 (
  echo.
  echo   پایتون روی این سیستم نصب نیست.
  echo   از سایت python.org نسخه 3.10 یا بالاتر را نصب کنید
  echo   و در هنگام نصب گزینه "Add python.exe to PATH" را تیک بزنید.
  echo.
  pause
  exit /b 1
)
python run.py %*
if errorlevel 1 pause
