#!/usr/bin/env python3
"""
راه‌انداز برنامه‌ی «تولید انبوه تصویر از قالب فتوشاپ».

این فایل:
  1) کتابخانه‌های لازم را بررسی (و در صورت نبود، نصب) می‌کند
  2) سرور محلی را اجرا و مرورگر را باز می‌کند

اجرا:  python run.py            (یا دوبار کلیک روی run.bat در ویندوز)
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
FROZEN = bool(getattr(sys, "frozen", False))  # اجرای نسخه‌ی exe
REQUIREMENTS = [
    ("numpy", "numpy>=1.24"),
    ("PIL", "pillow>=9.0"),
    ("openpyxl", "openpyxl>=3.1"),
    ("psd_tools", "psd-tools>=1.9.20"),
]
MIN_PYTHON = (3, 9)


def check_python() -> bool:
    if sys.version_info < MIN_PYTHON:
        print("!" * 60)
        print(f"این برنامه به پایتون {MIN_PYTHON[0]}.{MIN_PYTHON[1]} یا بالاتر نیاز دارد.")
        print(f"نسخه‌ی فعلی شما: {sys.version.split()[0]}")
        print("از سایت python.org نسخه‌ی جدید را نصب کنید (گزینه‌ی Add to PATH را تیک بزنید).")
        print("!" * 60)
        return False
    return True


def missing_packages() -> list[str]:
    missing = []
    for module, package in REQUIREMENTS:
        try:
            __import__(module)
        except Exception:
            missing.append(package)
    return missing


def install(packages: list[str]) -> bool:
    print("در حال نصب کتابخانه‌های لازم (فقط یک‌بار انجام می‌شود)…")
    commands = [
        [sys.executable, "-m", "pip", "install", "--upgrade", *packages],
        [sys.executable, "-m", "pip", "install", "--user", "--upgrade", *packages],
    ]
    for command in commands:
        try:
            result = subprocess.run(command, check=False)
            if result.returncode == 0 and not missing_packages():
                print("نصب کتابخانه‌ها با موفقیت انجام شد.\n")
                return True
        except Exception as exc:
            print("  ! نصب ناموفق بود:", exc)
    return False


def main() -> None:
    parser = argparse.ArgumentParser(description="راه‌انداز برنامه‌ی تولید انبوه تصویر")
    parser.add_argument("--port", type=int, default=int(os.environ.get("PSD_BATCH_PORT", 8756)))
    parser.add_argument("--host", default="127.0.0.1", help="آدرس شبکه (پیش‌فرض: فقط همین سیستم)")
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--skip-install", action="store_true")
    args = parser.parse_args()

    if FROZEN:
        # در نسخه‌ی بسته‌بندی‌شده، کتابخانه‌ها همراه فایل اجرایی هستند
        sys.path.insert(0, str(BASE_DIR))
        import server  # noqa: E402

        sys.argv = ["server.py", "--port", str(args.port), "--host", args.host]
        if args.no_browser:
            sys.argv.append("--no-browser")
        server.main()
        return

    if not check_python():
        input("\nبرای بستن Enter بزنید…")
        return

    missing = missing_packages()
    if missing:
        print("کتابخانه‌های زیر نصب نیستند:")
        for item in missing:
            print("   -", item)
        if args.skip_install:
            print("\nلطفاً دستی نصب کنید:  pip install " + " ".join(missing))
            input("\nبرای بستن Enter بزنید…")
            return
        answer = input("آیا الان نصب شوند؟ (بله/خیر) [بله]: ").strip().lower()
        if answer in ("", "بله", "ب", "y", "yes", "1"):
            if not install(missing):
                print("\nنصب خودکار ناموفق بود. لطفاً این دستور را در ترمینال اجرا کنید:")
                print("   pip install " + " ".join(missing))
                input("\nبرای بستن Enter بزنید…")
                return
        else:
            print("بدون نصب کتابخانه‌ها برنامه اجرا نمی‌شود.")
            input("\nبرای بستن Enter بزنید…")
            return

    sys.path.insert(0, str(BASE_DIR))
    import server  # noqa: E402  (بعد از بررسی کتابخانه‌ها)

    sys.argv = [
        "server.py",
        "--port", str(args.port),
        "--host", args.host,
    ]
    if args.no_browser:
        sys.argv.append("--no-browser")
    server.main()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nبرنامه بسته شد.")
