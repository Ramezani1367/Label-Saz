#!/usr/bin/env python3
"""ساخت فایل پیش‌نمایش سبک (HTML) و PDF چندصفحه‌ای از اسکرین‌شات‌های برنامه."""

from __future__ import annotations

import base64
import io
from pathlib import Path

from PIL import Image

PREVIEW = Path(__file__).resolve().parent.parent / "preview"

SHOTS = [
    ("تب ۱ — فایل‌های ورودی", "01-تب-۱-فایل‌ها.png",
     "انتخاب اکسل اطلاعات، قالب فتوشاپ، پوشه‌ی مقصد، فرمت خروجی و سطر عنوان‌ها"),
    ("تب ۱ — گزینه‌های خروجی PDF", "01b-خروجی-PDF.png",
     "سه حالت PDF: یکپارچه در هر پوشه، یکپارچه برای همه‌ی شیت‌ها، یا جدا‌جدا برای هر ردیف — به‌همراه تیک «PDF هر ردیف هم جداگانه ذخیره شود»"),
    ("تب ۲ — لایه‌های متنی", "02-تب-۲-لایه‌های-متنی.png",
     "هر لایه‌ی متنی با پلیس‌هولدرهای {{ستون}}؛ انتخاب حالت جایگزینی، جهت متن و ستون اکسل (تطبیق خودکار)"),
    ("تب ۳ — شیت‌ها و نام فایل", "03-تب-۳-شیت‌ها.png",
     "برای هر شیت: فعال/غیرفعال، دو ستون نام‌گذاری، جداکننده، بازه‌ی ردیف، قالب اختصاصی و نام پوشه — با نمونه‌ی زنده‌ی نام فایل"),
    ("تب ۴ — تنظیمات ظاهری", "04-تب-۴-تنظیمات-ظاهری.png",
     "دقت خروجی، فونت فارسی، کیفیت لبه‌ها، ضریب فونت و خطوط، رنگ و جابجایی متن، سبک لنگر"),
    ("تب ۵ — پیش‌نمایش و تولید", "05-تب-۵-اجرا.png",
     "انتخاب شیت و ردیف برای پیش‌نمایش، شروع تولید، توقف و باز کردن پوشه‌ی خروجی"),
    ("پیش‌نمایش یک ردیف", "06-پیش‌نمایش-ردیف.png",
     "تصویر خروجی همان ردیف + فهرست دقیق همه‌ی جایگزینی‌ها پیش از تولید انبوه"),
    ("انتخاب پوشه", "07-مرور-پوشه.png",
     "مرورگر پوشه‌ی داخلی برنامه؛ دقیقاً همان‌جایی که کاربر می‌خواهد خروجی ساخته شود"),
    ("در حال تولید", "08-در-حال-تولید.png",
     "درصد پیشرفت، نام فایل در حال ساخت، لاگ زنده و امکان توقف"),
    ("پایان تولید", "09-پایان-تولید.png",
     "۱۰۰٪ پیشرفت، گزارش «۷ فایل در ۲ شیت، ۰ خطا» و مسیر پوشه‌ی خروجی"),
    ("راهنمای داخل برنامه", "10-راهنما.png",
     "راهنمای فارسی قدم‌به‌قدم: پلیس‌هولدر، PDF، قالب اختصاصی هر شیت و کار با فونت فارسی"),
]


def jpeg_b64(path: Path, max_width: int = 1150, quality: int = 78) -> str:
    image = Image.open(path).convert("RGB")
    if image.width > max_width:
        image = image.resize((max_width, round(image.height * max_width / image.width)), Image.LANCZOS)
    buffer = io.BytesIO()
    image.save(buffer, "JPEG", quality=quality, optimize=True, progressive=True)
    return "data:image/jpeg;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")


HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="fa" dir="rtl">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>App preview — PSD batch generator</title>
<style>
  body {{ margin:0; background:#0f1620; color:#e8eef6; font-family:Tahoma,"Segoe UI",sans-serif; line-height:1.85; }}
  header {{ padding:22px 24px 14px; background:#16202c; border-bottom:1px solid #2c3d52; }}
  h1 {{ margin:0 0 6px; font-size:19px; }}
  header p {{ margin:0; color:#93a4b8; font-size:13px; }}
  main {{ max-width:1120px; margin:18px auto 50px; padding:0 14px; display:flex; flex-direction:column; gap:18px; }}
  figure {{ margin:0; background:#1b2634; border:1px solid #2c3d52; border-radius:14px; overflow:hidden; }}
  figcaption {{ padding:12px 16px; display:flex; flex-direction:column; gap:2px; }}
  figcaption b {{ color:#37b1ff; font-size:15px; }}
  figcaption span {{ color:#93a4b8; font-size:12.5px; }}
  img {{ display:block; width:100%; height:auto; border-top:1px solid #2c3d52; }}
</style>
</head>
<body>
<header>
  <h1>پیش‌نمایش برنامه‌ی تولید انبوه تصویر از قالب فتوشاپ</h1>
  <p>اسکرین‌شات واقعی از اجرای برنامه روی نمونه‌ها — ۷ فایل در ۲ شیت بدون خطا</p>
</header>
<main>{cards}
</main>
</body>
</html>
"""


def main() -> None:
    cards = []
    for title, filename, caption in SHOTS:
        path = PREVIEW / filename
        if not path.exists():
            continue
        cards.append(
            f"""
  <figure>
    <figcaption><b>{title}</b><span>{caption}</span></figcaption>
    <img src="{jpeg_b64(path)}" alt="{title}" />
  </figure>"""
        )

    html_path = PREVIEW / "app-preview.html"
    html_path.write_text(HTML_TEMPLATE.format(cards="".join(cards)), encoding="utf-8")

    pages = []
    for _title, filename, _caption in SHOTS:
        path = PREVIEW / filename
        if not path.exists():
            continue
        image = Image.open(path).convert("RGB")
        if image.width > 1400:
            image = image.resize((1400, round(image.height * 1400 / image.width)), Image.LANCZOS)
        pages.append(image)

    if pages:
        first, rest = pages[0], pages[1:]
        first.save(PREVIEW / "app-preview.pdf", save_all=True, append_images=rest, resolution=110, quality=72)

    print("HTML:", html_path.name, round(html_path.stat().st_size / 1024), "KB")
    pdf_path = PREVIEW / "app-preview.pdf"
    if pdf_path.exists():
        print("PDF:", pdf_path.name, round(pdf_path.stat().st_size / 1024), "KB", f"({len(pages)} صفحه)")


if __name__ == "__main__":
    main()
