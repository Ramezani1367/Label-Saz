#!/usr/bin/env python3
"""
نسخه‌ی ویندوزی برنامه — «بدون پنجره‌ی سیاه CMD».

این فایل نقطه‌ی ورود فایل اجرایی ساخته‌شده با PyInstaller است (بخش packaging/):

  * در حالت پنجره‌ای (windowed) خروجی کنسول وجود ندارد؛ همه‌ی پیام‌ها در فایل
    psd-batch.log کنار برنامه ذخیره می‌شوند.
  * سرور محلی در پس‌زمینه بالا می‌آید و مرورگر خودکار باز می‌شود.
  * یک پنجره‌ی کوچک کنترل نمایش داده می‌شود: «باز کردن مرورگر» و «بستن برنامه».

اجرای مستقیم از سورس در ویندوز:  آن را با pythonw اجرا کنید (یا run_windows.bat).
"""

from __future__ import annotations

import os
import queue
import sys
import threading
import time
import traceback
import webbrowser
from pathlib import Path

APP_TITLE = "تولید انبوه تصویر از قالب فتوشاپ"
CONTROL_STATE: dict = {"ready": False}

# صف درخواست‌های «انتخاب فایل/پوشه» — بین ترد سرور و ترد رابط گرافیکی
DIALOG_QUEUE: "queue.Queue[tuple]" = queue.Queue()
DIALOG_TIMEOUT = 300
# برچسب انگلیسی برای پیام‌های کنسول (ویندوز با cp1252 نمی‌تواند فارسی چاپ کند)
LOG_TAG = "[PSD-Batch-Generator]"
DEFAULT_PORT = 8756
PORT_TRIES = 12


# ------------------------------------------------------------------ کمکی‌ها

def base_dir() -> Path:
    """پوشه‌ی برنامه: کنار فایل اجرایی (نسخه‌ی exe) یا پوشه‌ی سورس."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def setup_logging() -> Path:
    """خروجی‌ها را ایمن می‌کند و لاگ را آماده می‌کند.

    * اگر stdout/stderr وجود داشته باشند (اجرا از داخل CMD)، کدگذاری‌شان طوری
      تنظیم می‌شود که متن فارسی باعث خطای cp1252 نشود.
    * اگر وجود نداشته باشند (حالت exe بدون کنسول)، به فایل لاگ UTF-8 وصل می‌شوند.
    * اگر ساخت فایل لاگ ممکن نبود، از یک جریان بی‌اثر استفاده می‌شود.
    """
    import io

    from engine.console import harden_stdio

    harden_stdio()
    log_path = base_dir() / "psd-batch.log"
    stream = None
    try:
        stream = open(log_path, "a", encoding="utf-8", buffering=1)
    except Exception:
        stream = io.StringIO()

    if sys.stdout is None:
        sys.stdout = stream
    if sys.stderr is None:
        sys.stderr = stream
    return log_path


def install_excepthooks(log_path: Path) -> None:
    """خطاهای پیش‌بینی‌نشده را در فایل لاگ می‌نویسد و پیام قابل‌فهم نشان می‌دهد.

    (به‌جای پنجره‌ی خام traceback که PyInstaller نشان می‌دهد)
    """

    def handle(exc_type, exc_value, exc_tb) -> None:
        text = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
        try:
            with open(log_path, "a", encoding="utf-8") as handle_:
                handle_.write(text + "\n")
        except Exception:
            pass
        message_box(
            APP_TITLE,
            "خطای غیرمنتظره‌ای رخ داد.\n\n"
            + text.strip().splitlines()[-1][:300]
            + f"\n\nفایل لاگ (برای ارسال به پشتیبانی):\n{log_path}",
            error=True,
        )

    sys.excepthook = handle
    threading.excepthook = lambda args: handle(args.exc_type, args.exc_value, args.exc_traceback)


def message_box(title: str, text: str, error: bool = False) -> None:
    """نمایش پیام به کاربر، بدون نیاز به کنسول."""
    try:
        import tkinter as tk
        from tkinter import messagebox

        root = tk.Tk()
        root.withdraw()
        (messagebox.showerror if error else messagebox.showinfo)(title, text)
        root.destroy()
        return
    except Exception:
        pass
    try:
        import ctypes

        ctypes.windll.user32.MessageBoxW(0, text, title, 0x10 if error else 0x40)
    except Exception:
        try:
            from engine.console import safe_print

            safe_print(LOG_TAG, "message:", text.encode("ascii", "replace").decode("ascii"))
        except Exception:
            pass


def start_server(port: int):
    """سرور محلی را می‌سازد؛ اگر پورت اشغال بود، پورت‌های بعدی را امتحان می‌کند."""
    import server

    last_error: Exception | None = None
    for candidate in range(port, port + PORT_TRIES):
        try:
            return server.build_server("127.0.0.1", candidate), candidate
        except OSError as exc:
            last_error = exc
    raise RuntimeError(
        f"هیچ پورت آزادی بین {port} و {port + PORT_TRIES - 1} پیدا نشد.\n{last_error}"
    )


def native_dialog(mode: str, title: str, extensions: list[str] | None) -> dict:
    """پنجره‌ی انتخاب فایل/پوشه را در ترد رابط گرافیکی باز می‌کند.

    سرور در ترد جداگانه اجرا می‌شود؛ این تابع درخواست را به صف می‌گذارد و
    منتظر جواب می‌ماند. اگر پنجره‌ی کنترلی باز نباشد (tkinter نبود)،
    مقدار None برمی‌گردد تا مسیر درون‌برنامه‌ای امتحان شود.
    """
    if not CONTROL_STATE.get("ready"):
        return None
    box: dict = {}
    DIALOG_QUEUE.put((mode, title, extensions, box))
    deadline = time.time() + DIALOG_TIMEOUT
    while time.time() < deadline:
        if "path" in box or "error" in box:
            break
        time.sleep(0.08)
    if "path" in box:
        return {"ok": True, "path": box["path"]}
    if "error" in box:
        return {"ok": False, "error": box["error"]}
    return {"ok": False, "error": "مهلت انتخاب فایل تمام شد."}


def _serve_dialog_requests(root) -> None:
    """هر ۱۵۰ میلی‌ثانیه صف را بررسی می‌کند و دیالوگ را در ترد اصلی باز می‌کند."""
    from tkinter import filedialog

    try:
        mode, title, extensions, box = DIALOG_QUEUE.get_nowait()
    except queue.Empty:
        root.after(150, lambda: _serve_dialog_requests(root))
        return

    try:
        root.attributes("-topmost", True)
        root.update()
    except Exception:
        pass

    try:
        if mode == "dir":
            path = filedialog.askdirectory(title=title or "انتخاب پوشه", parent=root)
        else:
            types = [("همه فایل‌ها", "*.*")]
            if extensions:
                types = [(ext.upper().lstrip("."), "*" + ext) for ext in extensions] + types
            path = filedialog.askopenfilename(title=title or "انتخاب فایل", filetypes=types, parent=root)
        box["path"] = (path or "").strip()
    except Exception as exc:
        box["error"] = str(exc)

    # پنجره‌ی کنترل عمداً روی بقیه‌ی پنجره‌ها می‌ماند تا گم نشود
    root.after(150, lambda: _serve_dialog_requests(root))


def control_window(url: str, httpd, icon_path: Path | None) -> None:
    """پنجره‌ی کوچک کنترل برنامه (اگر tkinter موجود نباشد، بی‌صدا اجرا می‌شود)."""
    from engine.console import safe_print

    try:
        import tkinter as tk
        from tkinter import font as tkfont

        root = tk.Tk()
        CONTROL_STATE["ready"] = True
        root.after(150, lambda: _serve_dialog_requests(root))
    except Exception:
        # بدون tkinter (یا بدون نمایشگر) برنامه باز هم بی‌صدا کار می‌کند
        safe_print(LOG_TAG, "tkinter is not available; running without the control window.", flush=True)
        httpd.serve_forever()
        return

    root.title(APP_TITLE)
    root.geometry("500x230")
    root.resizable(False, False)
    if icon_path and icon_path.exists():
        try:
            root.iconbitmap(default=str(icon_path))
        except Exception:
            pass

    title_font = tkfont.Font(family="Tahoma", size=11, weight="bold")
    body_font = tkfont.Font(family="Tahoma", size=9)

    tk.Label(root, text="برنامه در حال اجراست ✅", font=title_font, fg="#15803d").pack(pady=(18, 6))
    tk.Label(
        root,
        text="رابط برنامه در مرورگر باز شد. این پنجره را باز بگذارید؛\nبرای پایان کار، «بستن برنامه» را بزنید.",
        font=body_font,
        fg="#334155",
        justify="center",
    ).pack()

    link = tk.Entry(root, font=body_font, justify="center", relief="flat", fg="#2563eb")
    link.insert(0, url)
    link.configure(state="readonly", readonlybackground="#eef4ff", width=46)
    link.pack(pady=10)

    buttons = tk.Frame(root)
    buttons.pack(pady=4)

    def open_browser() -> None:
        webbrowser.open(url)

    def close() -> None:
        CONTROL_STATE["ready"] = False
        try:
            httpd.shutdown()
        finally:
            root.destroy()

    tk.Button(buttons, text="باز کردن مرورگر", font=body_font, bg="#2563eb", fg="white", width=16, command=open_browser, cursor="hand2").pack(side="left", padx=6)
    tk.Button(buttons, text="بستن برنامه", font=body_font, bg="#e2e8f0", width=14, command=close, cursor="hand2").pack(side="left", padx=6)

    root.protocol("WM_DELETE_WINDOW", close)
    root.mainloop()


def main() -> int:
    log_path = setup_logging()
    root_dir = base_dir()
    sys.path.insert(0, str(root_dir))

    from engine.console import safe_print

    install_excepthooks(log_path)

    try:
        import server
        from engine.paths import resource_dir
    except Exception:
        message_box(APP_TITLE, "کتابخانه‌های برنامه پیدا نشد.\n\n" + traceback.format_exc()[-900:], error=True)
        return 1

    server.set_dialog_provider(native_dialog)  # پنجره‌ی انتخاب فایل در ترد رابط گرافیکی

    port = int(os.environ.get("PSD_BATCH_PORT", DEFAULT_PORT))
    try:
        httpd, port = start_server(port)
    except Exception as exc:
        message_box(
            APP_TITLE,
            f"{exc}\n\nمی‌توانید برنامه‌ی دیگری را ببندید یا متغیر محیطی PSD_BATCH_PORT را روی پورت دیگری تنظیم کنید.",
            error=True,
        )
        return 1

    url = f"http://127.0.0.1:{port}/"

    # ۱) اول سرور روشن می‌شود تا هیچ خطای بعدی (چاپ/پنجره/مرورگر) برنامه را از کار نیندازد
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    safe_print(LOG_TAG, "running at", url, "| log:", log_path, flush=True)

    # ۲) باز کردن مرورگر (اگر نشد، آدرس در پنجره‌ی کنترل و لاگ هست)
    try:
        webbrowser.open(url)
    except Exception as exc:
        safe_print(LOG_TAG, "could not open the browser:", exc, flush=True)

    # ۳) پنجره‌ی کنترل؛ اگر رابط گرافیکی کار نکرد، سرور در همین ترد ادامه می‌دهد
    try:
        control_window(url, httpd, resource_dir() / "packaging" / "icon.ico")
    except Exception as exc:
        safe_print(LOG_TAG, "control window failed:", exc, flush=True)
        httpd.serve_forever()

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(0)
