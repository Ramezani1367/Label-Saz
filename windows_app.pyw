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
import sys
import threading
import traceback
import webbrowser
from pathlib import Path

APP_TITLE = "تولید انبوه تصویر از قالب فتوشاپ"
DEFAULT_PORT = 8756
PORT_TRIES = 12


# ------------------------------------------------------------------ کمکی‌ها

def base_dir() -> Path:
    """پوشه‌ی برنامه: کنار فایل اجرایی (نسخه‌ی exe) یا پوشه‌ی سورس."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def setup_logging() -> Path:
    """در حالت پنجره‌ای، stdout/stderr وجود ندارند؛ به فایل لاگ وصل می‌شوند."""
    log_path = base_dir() / "psd-batch.log"
    try:
        stream = open(log_path, "a", encoding="utf-8", buffering=1)
    except Exception:
        return log_path
    if sys.stdout is None:
        sys.stdout = stream
    if sys.stderr is None:
        sys.stderr = stream
    return log_path


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
        print(f"{title}: {text}")


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


def control_window(url: str, httpd, icon_path: Path | None) -> None:
    """پنجره‌ی کوچک کنترل برنامه (اگر tkinter موجود نباشد، بی‌صدا اجرا می‌شود)."""
    try:
        import tkinter as tk
        from tkinter import font as tkfont

        root = tk.Tk()
    except Exception:
        # بدون tkinter (یا بدون نمایشگر) برنامه باز هم بی‌صدا کار می‌کند
        print("tkinter در دسترس نیست؛ برنامه بدون پنجره‌ی کنترل اجرا می‌شود.", flush=True)
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

    try:
        import server
        from engine.paths import resource_dir
    except Exception:
        message_box(APP_TITLE, "کتابخانه‌های برنامه پیدا نشد.\n\n" + traceback.format_exc()[-900:], error=True)
        return 1

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
    print(f"[{APP_TITLE}] {url}  (log: {log_path})", flush=True)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    webbrowser.open(url)
    control_window(url, httpd, resource_dir() / "packaging" / "icon.ico")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(0)
