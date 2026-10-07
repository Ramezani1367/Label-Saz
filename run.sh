#!/usr/bin/env bash
# اجرای برنامه روی لینوکس/مک
cd "$(dirname "$0")" || exit 1
if command -v python3 >/dev/null 2>&1; then
  exec python3 run.py "$@"
else
  echo "پایتون ۳ نصب نیست. لطفاً نصب کنید: sudo apt install python3 python3-pip python3-tk"
  exit 1
fi
