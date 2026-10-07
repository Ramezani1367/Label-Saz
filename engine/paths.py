"""
مسیرهای برنامه — هم برای اجرای معمولی (python run.py) و هم برای نسخه‌ی
بسته‌بندی‌شده‌ی ویندوز (exe ساخته‌شده با PyInstaller).

- resource_dir(): فایل‌های همراه برنامه (web/، fonts/، samples/، docs/)
- app_dir():      فایل‌های کاربر (settings.json، psd-batch.log، خروجی پیش‌فرض)

در حالت exe، فایل‌های همراه داخل پوشه‌ی برنامه هستند (sys._MEIPASS) و
فایل‌های کاربر کنار خود exe ساخته می‌شوند؛ اگر آن پوشه قابل‌نوشتن نبود
(مثلاً نصب در Program Files) به پوشه‌ی کاربر در ویندوز منتقل می‌شود.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

APP_NAME = "PSD-Batch-Generator"


def is_frozen() -> bool:
    """آیا برنامه به‌صورت فایل اجرایی (exe) اجرا شده است؟"""
    return bool(getattr(sys, "frozen", False))


def resource_dir() -> Path:
    """پوشه‌ی فایل‌های همراه برنامه (فقط خواندنی)."""
    if is_frozen():
        base = getattr(sys, "_MEIPASS", None)
        if base:
            return Path(base)
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def _is_writable(folder: Path) -> bool:
    try:
        folder.mkdir(parents=True, exist_ok=True)
        probe = folder / ".psd-batch-write-test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        return True
    except Exception:
        return False


def app_dir() -> Path:
    """پوشه‌ی فایل‌های کاربر (settings.json و لاگ)."""
    if is_frozen():
        beside_exe = Path(sys.executable).resolve().parent
        if _is_writable(beside_exe):
            return beside_exe
        fallback = Path(os.environ.get("APPDATA") or Path.home()) / APP_NAME
        fallback.mkdir(parents=True, exist_ok=True)
        return fallback
    return Path(__file__).resolve().parent.parent


def user_file(name: str) -> Path:
    """مسیر یک فایل کاربر (مثلاً settings.json)."""
    return app_dir() / name


def user_dir(name: str, create: bool = True) -> Path:
    """مسیر یک پوشه‌ی کاربر (مثلاً fonts/ یا خروجی‌ها)."""
    path = app_dir() / name
    if create:
        path.mkdir(parents=True, exist_ok=True)
    return path


def font_dir() -> Path:
    """پوشه‌ی فونت‌های کاربر: کنار برنامه (اگر قابل‌نوشتن باشد) وگرنه پوشه‌ی همراه."""
    fallback = user_dir("fonts")
    if _is_writable(fallback):
        return fallback
    return resource_dir() / "fonts"
