"""
ابزارهای ایمن کنسول — برای وقتی برنامه روی ویندوز اجرا می‌شود.

مشکل: در ویندوز، جریان‌های خروجی (stdout/stderr) ممکن است با کدگذاری
`cp1252` باز شوند. در این حالت هر `print` با متن فارسی (یا نام فایل فارسی)
باعث خطای زیر می‌شود و برنامه را از کار می‌اندازد:

    UnicodeEncodeError: 'charmap' codec can't encode characters ...

راه‌حل: با `harden_stdio()` خطاهای کدگذاری به «?» تبدیل می‌شوند (به‌جای پرتاب
استثنا) و اگر جریان خروجی وجود نداشت (حالت exe بدون کنسول)، `safe_print()`
بی‌صدا رد می‌شود. متن کامل همیشه در فایل لاگ (UTF-8) می‌ماند.
"""

from __future__ import annotations

import sys
from typing import Any

HARDENED = False


def harden_stdio() -> None:
    """جریان‌های خروجی را طوری تنظیم می‌کند که چاپ متن غیرلاتین هیچ‌وقت خطا ندهد."""
    global HARDENED
    if HARDENED:
        return
    for name in ("stdout", "stderr"):
        stream = getattr(sys, name, None)
        if stream is None:
            continue
        try:
            stream.reconfigure(errors="replace")  # type: ignore[attr-defined]
        except Exception:
            pass
    HARDENED = True


def safe_print(*parts: Any, **kwargs: Any) -> None:
    """نسخه‌ی خطاناپذیر print؛ اگر جریان خروجی نباشد یا کدگذاری نکشد، بی‌صدا رد می‌شود."""
    harden_stdio()
    try:
        print(*parts, **kwargs)
        return
    except Exception:
        pass
    try:
        text = " ".join(str(part) for part in parts)
        stream = getattr(sys, "stdout", None)
        if stream is None:
            return
        ascii_text = text.encode("ascii", "replace").decode("ascii")
        stream.write(ascii_text + ("\n" if kwargs.get("end", "\n") == "\n" else str(kwargs.get("end"))))
        try:
            stream.flush()
        except Exception:
            pass
    except Exception:
        pass
