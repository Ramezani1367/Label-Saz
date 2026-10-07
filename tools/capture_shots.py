#!/usr/bin/env python3
"""گرفتن اسکرین‌شات‌های تازه از رابط برنامه (برای پوشه‌ی preview/).

پیش‌نیاز (فقط برای توسعه‌دهنده):

    pip install playwright
    python3 -m playwright install chromium

اجرا (برنامه باید روی پورت ۸۷۵۶ در حال اجرا باشد):

    python3 tools/capture_shots.py               # پورت پیش‌فرض ۸۷۵۶
    python3 tools/capture_shots.py --port 9000   # پورت دلخواه

خروجی: تصاویر 01-…10- در پوشه‌ی preview/؛ سپس برای ساخت HTML/PDF:

    python3 tools/make_preview.py
"""

from __future__ import annotations

import argparse
import os
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = Path(__file__).resolve().parent.parent
OUT = BASE / "preview"


def shot(page, name: str, full: bool = False) -> None:
    path = OUT / name
    page.screenshot(path=str(path), full_page=full)
    print("  ✔", name, round(path.stat().st_size / 1024), "KB")


def main() -> None:
    parser = argparse.ArgumentParser(description="اسکرین‌شات از رابط برنامه")
    parser.add_argument("--port", type=int, default=8756)
    parser.add_argument("--host", default="127.0.0.1")
    args = parser.parse_args()
    url = f"http://{args.host}:{args.port}/"

    OUT.mkdir(parents=True, exist_ok=True)
    for stale in OUT.glob("*.png"):
        stale.unlink()

    executable = os.environ.get("CHROME_PATH") or None
    with sync_playwright() as p:
        browser = p.chromium.launch(
            executable_path=executable,
            args=["--no-sandbox", "--disable-dev-shm-usage", "--font-render-hinting=none"],
        )
        context = browser.new_context(
            viewport={"width": 1480, "height": 940},
            device_scale_factor=1.5,
            locale="fa-IR",
        )
        page = context.new_page()
        page.goto(url, wait_until="networkidle")
        page.wait_for_function(
            "() => { const b = document.querySelector('#badgeSheets'); return b && b.textContent.trim().length > 0; }",
            timeout=60000,
        )
        page.wait_for_timeout(600)

        # تب ۱ — فایل‌ها
        page.click('.tab[data-tab="files"]')
        page.wait_for_timeout(400)
        shot(page, "01-تب-۱-فایل‌ها.png")

        # تب ۱ — گزینه‌های خروجی PDF (یکپارچه / همه‌ی شیت‌ها / جدا‌جدا)
        page.select_option("#imageFormat", "pdf")
        page.select_option("#pdfMode", "all")
        page.wait_for_timeout(400)
        shot(page, "01b-خروجی-PDF.png")
        page.select_option("#imageFormat", "png")
        page.wait_for_timeout(300)

        # تب ۲ — لایه‌های متنی
        page.click('.tab[data-tab="layers"]')
        page.wait_for_timeout(400)
        shot(page, "02-تب-۲-لایه‌های-متنی.png", full=True)

        # تب ۳ — شیت‌ها و نام فایل
        page.click('.tab[data-tab="sheets"]')
        page.wait_for_timeout(400)
        shot(page, "03-تب-۳-شیت‌ها.png", full=True)

        # تب ۴ — تنظیمات ظاهری
        page.click('.tab[data-tab="settings"]')
        page.wait_for_timeout(400)
        shot(page, "04-تب-۴-تنظیمات-ظاهری.png")

        # تب ۵ — اجرا و خروجی (پیش از اجرا)
        page.click('.tab[data-tab="run"]')
        page.wait_for_timeout(400)
        shot(page, "05-تب-۵-اجرا.png")

        # پیش‌نمایش یک ردیف
        page.click("#btnPreview")
        page.wait_for_selector("#previewBox img", timeout=60000)
        page.wait_for_timeout(700)
        shot(page, "06-پیش‌نمایش-ردیف.png", full=True)

        # مرورگر پوشه
        page.evaluate("openBrowser('dir')")
        page.wait_for_timeout(900)
        shot(page, "07-مرور-پوشه.png")
        page.click("#browserClose")

        # در حال تولید + پایان تولید
        page.click("#btnStart")
        mid_done = False
        deadline = time.time() + 40
        while time.time() < deadline:
            percent = page.eval_on_selector("#progressPercent", "el => el.textContent").strip()
            if not mid_done and percent not in ("۰٪", "", "۱۰۰٪"):
                shot(page, "08-در-حال-تولید.png")
                mid_done = True
            if percent == "۱۰۰٪":
                break
            page.wait_for_timeout(120)
        page.wait_for_timeout(800)
        if not mid_done:
            print("  ! لحظه‌ی میانی تولید ثبت نشد")
        shot(page, "09-پایان-تولید.png", full=True)

        # راهنما
        page.click("#btnHelp")
        page.wait_for_timeout(700)
        shot(page, "10-راهنما.png")
        page.click("#helpClose")

        browser.close()

    print("\nحالا برای ساخت HTML/PDF پیش‌نمایش:  python3 tools/make_preview.py")


if __name__ == "__main__":
    main()
