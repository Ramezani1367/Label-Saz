#!/usr/bin/env python3
"""بازتولید خطای کاربر و بررسی رفع آن.

۱) ابتدا نشان می‌دهد مشکل اصلی چه بود: print متن فارسی روی جریانی با کدگذاری cp1252.
۲) سپس همان کار را با ابزار ایمن جدید (engine.console) انجام می‌دهد.
۳) در پایان، فایل exe ساخته‌شده را در همان شرایط (PYTHONIOENCODING=cp1252، خروجی به فایل)
   اجرا می‌کند و بررسی می‌کند که بالا بیاید و صفحه‌ی رابط را سرو کند.
"""

from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

BASE = Path("/home/user/psd-batch-generator")
sys.path.insert(0, str(BASE))
FAILED = 0


def check(title: str, ok: bool, detail: str = "") -> None:
    global FAILED
    print(("✅ " if ok else "❌ ") + title + (f" — {detail}" if detail else ""))
    if not ok:
        FAILED += 1


def cp1252_stream() -> io.TextIOWrapper:
    """جریانی شبیه کنسول ویندوز (cp1252) که خروجی‌اش به جایی نمی‌رود."""
    return io.TextIOWrapper(io.BytesIO(), encoding="cp1252", newline="")


def main() -> int:
    from engine.console import harden_stdio, safe_print

    # ۱) همان کدی که کرش می‌کرد
    print("— ۱) بازتولید خطای اصلی (چاپ فارسی روی کدگذاری cp1252) —")
    stream = cp1252_stream()
    original = sys.stdout
    sys.stdout = stream
    crashed = False
    try:
        print("[تولید انبوه تصویر از قالب فتوشاپ] http://127.0.0.1:8756/")
    except UnicodeEncodeError:
        crashed = True
    finally:
        sys.stdout = original
    check("خطای cp1252 با روش قدیمی بازتولید شد", crashed, "UnicodeEncodeError")

    # ۲) همان شرایط، با ابزار جدید
    print("\n— ۲) همان شرایط با engine.console —")
    stream = cp1252_stream()
    sys.stdout = stream
    errored = False
    try:
        safe_print("[PSD-Batch-Generator] running at http://127.0.0.1:8756/ | log: C:\\کار\\psd-batch.log")
    except Exception as exc:  # نباید پیش بیاید
        errored = True
        print("EXC", exc)
    finally:
        sys.stdout = original
    check("safe_print روی cp1252 خطا نمی‌دهد", not errored)
    check("متن غیرقابل‌کدگذاری با ? جایگزین شد",
          "?" in stream.detach().getvalue().decode("cp1252", "replace"))

    # ۳) جریان نداشتن (حالت exe بدون کنسول) نباید خطا بدهد
    sys.stdout = None
    try:
        safe_print("no stream here")
        ok = True
    except Exception:
        ok = False
    finally:
        sys.stdout = original
    check("safe_print بدون جریان خروجی هم امن است", ok)

    # ۴) اجرای exe ساخته‌شده در شرایط دقیق کاربر
    exe_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    if exe_dir:
        print("\n— ۴) اجرای exe در همان شرایط (cp1252 + خروجی ریدایرکت‌شده) —")
        exe = exe_dir / "PSD-Batch-Generator"
        port = 8798
        environment = {
            **os.environ,
            "PYTHONIOENCODING": "cp1252",   # ← همان چیزی که برنامه را می‌ترکاند
            "PSD_BATCH_PORT": str(port),
        }
        log_file = open("/tmp/frozen_run_stdout.log", "wb")
        process = subprocess.Popen(
            [str(exe)], stdout=log_file, stderr=subprocess.STDOUT, env=environment,
            cwd=str(exe_dir), start_new_session=True,
        )
        time.sleep(9)
        alive = process.poll() is None
        check("exe با کنسول cp1252 زنده می‌ماند (کرش نمی‌کند)", alive,
              "کد خروج: " + str(process.poll()) if not alive else "")
        served = False
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=8) as response:
                body = response.read().decode("utf-8")
                served = response.status == 200 and "app.js" in body
        except Exception as exc:
            print("   خطای دسترسی:", exc)
        check("رابط برنامه سرو می‌شود", served)

        # انتخاب فایل در حالت exe نباید نمونه‌ی دومی بالا بیاورد
        before = subprocess.run(["pgrep", "-fc", "PSD-Batch-Generator"], capture_output=True, text=True).stdout.strip()
        request = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/pick?mode=file&title=test&ext=.psd",
        )
        started = time.time()
        try:
            payload = json.load(urllib.request.urlopen(request, timeout=20))
        except Exception as exc:
            payload = {"ok": False, "error": str(exc)}
        elapsed = time.time() - started
        after = subprocess.run(["pgrep", "-fc", "PSD-Batch-Generator"], capture_output=True, text=True).stdout.strip()
        check("/api/pick سریع جواب می‌دهد (نمونه‌ی دومی بالا نمی‌آید)", elapsed < 15,
              f"{elapsed:.1f} ثانیه، answer={payload}")
        check("تعداد پروسه‌ها زیاد نشد", before == after, f"قبل {before} → بعد {after}")

        try:
            process.terminate()
        except Exception:
            pass
        log_file.close()
        text = Path("/tmp/frozen_run_stdout.log").read_text("utf-8", "replace")
        clean = "UnicodeEncodeError" not in text and "Traceback" not in text
        check("خروجی exe بدون UnicodeEncodeError/Traceback", clean,
              text.strip().splitlines()[-1][:80] if text.strip() else "خروجی خالی")

    print("\n" + "=" * 56)
    if FAILED:
        print(f"❌ {FAILED} مورد ناموفق")
        return 1
    print("✅ همه‌ی بررسی‌ها موفق — خطای کاربر رفع شد.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
