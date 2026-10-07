#!/usr/bin/env python3
"""
ساخت صفحه‌ی معرفی تک‌فایلی HTML (docs/index.html) برای گیت‌هاب / GitHub Pages.

این صفحه کاملاً خودبسنده است (بدون فایل بیرونی، بدون اینترنت) و اسکرین‌شات‌های
برنامه را به‌صورت تصویر جاسازی‌شده درون خود دارد. می‌شود آن را روی GitHub Pages
منتشر کرد (Settings → Pages → Branch: main, Folder: /docs).

اجرا:  python3 tools/make_landing.py
"""

from __future__ import annotations

import base64
import io
from pathlib import Path

from PIL import Image

BASE = Path(__file__).resolve().parent.parent
PREVIEW = BASE / "preview"
TARGET = BASE / "docs" / "index.html"

SHOTS = [
    ("تب ۱ — فایل‌ها", "01-تب-۱-فایل‌ها.png",
     "اکسل، قالب PSD و پوشه‌ی مقصد را می‌دهید و «بررسی و بارگذاری فایل‌ها» را می‌زنید."),
    ("گزینه‌های خروجی PDF", "01b-خروجی-PDF.png",
     "سه حالت PDF: یکپارچه در هر پوشه، یکپارچه برای همه‌ی شیت‌ها، یا جدا جدا برای هر ردیف — و تیک «PDF هر ردیف هم جداگانه ذخیره شود»."),
    ("تب ۲ — لایه‌های متنی", "02-تب-۲-لایه‌های-متنی.png",
     "هر لایه با پلیس‌هولدرهای {{ستون}}؛ حالت جایگزینی، جهت متن و ستون اکسل (تطبیق خودکار)."),
    ("تب ۳ — شیت‌ها و نام فایل", "03-تب-۳-شیت‌ها.png",
     "برای هر شیت: دو ستون نام‌گذاری، جداکننده، بازه‌ی ردیف، قالب اختصاصی و نام پوشه — با نمونه‌ی زنده."),
    ("تب ۵ — اجرا و خروجی", "05-تب-۵-اجرا.png",
     "پیش‌نمایش یک ردیف، سپس تولید انبوه با درصد پیشرفت، لاگ زنده و دکمه‌ی توقف."),
    ("پایان تولید", "09-پایان-تولید.png",
     "گزارش نهایی: تعداد فایل‌ها، خطاها و مسیر پوشه‌ی خروجی."),
]

FEATURES = [
    ("پلیس‌هولدر داخل متن", "داخل متن لایه‌های فتوشاپ می‌نویسید <code>{{نام و نام خانوادگی}}</code> و برنامه با ستون هم‌نام در اکسل تطبیق می‌دهد."),
    ("چند شیت، چند قالب", "هر شیت اکسل یک پوشه با همان نام می‌گیرد؛ برای هر شیت می‌توانید قالب PSD، ستون‌های نام فایل و بازه‌ی ردیف جدا بدهید."),
    ("خروجی PNG / JPG / WEBP", "برای هر ردیف یک تصویر، با دقت دلخواه (تا ۳۰۰٪) و کیفیت لبه‌های قابل تنظیم."),
    ("خروجی PDF سه‌حالته", "یکپارچه در هر پوشه، یکپارچه برای همه‌ی شیت‌ها، یا جدا برای هر ردیف — همراه با فهرست CSV."),
    ("فونت فارسی", "شکل‌دهی صحیح فارسی/عربی با HarfBuzz؛ انتخاب فونت جانشین یا افزودن فایل فونت."),
    ("نسخه‌ی ویندوزی", "ساخت exe بدون پنجره‌ی CMD و با آیکون، هم روی گیت‌هاب (Actions) و هم روی ویندوز خودتان."),
]

PDF_ROWS = [
    ("یکپارچه — در هر پوشه یک PDF", "<code>پوشه‌ی مقصد/کارت ویزیت/کارت ویزیت.pdf</code> (۴ صفحه)"),
    ("یکپارچه — یک PDF برای همه‌ی شیت‌ها", "<code>پوشه‌ی مقصد/همه-صفحات.pdf</code> (همه‌ی ردیف‌ها پشت‌سرهم)"),
    ("جدا جدا — یک PDF برای هر ردیف", "<code>پوشه‌ی مقصد/کارت ویزیت/سارا محمدی-مدیر فروش.pdf</code> (تک‌صفحه)"),
    ("تیک «PDF هر ردیف هم جداگانه ساخته شود»", "هر دو خروجی با هم: یکپارچه + فایل جداگانه‌ی هر ردیف"),
]

RUN_STEPS = [
    ("۱) با گیت‌هاب (بدون نصب چیزی)", "ریپازیتوری را push کنید؛ ورک‌فلو <code>build-windows</code> خودش exe را می‌سازد و در تب Actions → Artifacts می‌گذارد. با تگ <code>v1.0.0</code> در Releases هم منتشر می‌شود."),
    ("۲) ساخت روی ویندوز خودتان", "دوبار کلیک روی <code>packaging/build_windows.bat</code> → <code>dist\\PSD-Batch-Generator\\PSD-Batch-Generator.exe</code>"),
    ("۳) اجرا از سورس بدون CMD", "دوبار کلیک روی <code>run_windows.bat</code>؛ پنجره‌ی سیاه باز نمی‌شود و مرورگر خودکار می‌آید."),
]


def embed(path: Path, width: int = 1000, quality: int = 72) -> str:
    image = Image.open(path).convert("RGB")
    if image.width > width:
        image = image.resize((width, round(image.height * width / image.width)), Image.LANCZOS)
    buffer = io.BytesIO()
    image.save(buffer, "JPEG", quality=quality, optimize=True, progressive=True)
    return "data:image/jpeg;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")


def main() -> None:
    cards = []
    for title, filename, caption in SHOTS:
        shot = PREVIEW / filename
        if not shot.exists():
            continue
        cards.append(
            f"""      <figure class="shot">
        <figcaption><b>{title}</b><span>{caption}</span></figcaption>
        <img src="{embed(shot)}" alt="{title}" loading="lazy" />
      </figure>"""
        )

    features = "\n".join(
        f"""        <div class="card"><h3>{title}</h3><p>{body}</p></div>""" for title, body in FEATURES
    )
    pdf_rows = "\n".join(f"""          <tr><td>{name}</td><td>{result}</td></tr>""" for name, result in PDF_ROWS)
    run_rows = "\n".join(f"""        <div class="step"><b>{title}</b><p>{body}</p></div>""" for title, body in RUN_STEPS)

    html = f"""<!DOCTYPE html>
<html lang="fa" dir="rtl">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>تولید انبوه تصویر از قالب فتوشاپ — معرفی برنامه</title>
<style>
  :root {{
    --bg:#f4f7fb; --surface:#ffffff; --surface-2:#f8fafc; --border:#e3e8f0;
    --text:#0f172a; --text-2:#475569; --primary:#2563eb; --primary-dark:#1d4ed8; --primary-soft:#eef4ff;
  }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; background:var(--bg); color:var(--text); font-family:Tahoma,"Segoe UI",sans-serif; line-height:1.9; }}
  header {{ background:linear-gradient(135deg,#2563eb,#1d4ed8); color:#fff; padding:38px 22px 30px; }}
  .wrap {{ max-width:1080px; margin:0 auto; padding:0 18px; }}
  header h1 {{ margin:0 0 8px; font-size:26px; }}
  header p {{ margin:0; opacity:.92; font-size:14.5px; }}
  .badges {{ display:flex; flex-wrap:wrap; gap:8px; margin-top:16px; }}
  .badge {{ background:rgba(255,255,255,.18); border:1px solid rgba(255,255,255,.35); border-radius:999px; padding:4px 12px; font-size:12.5px; }}
  main {{ padding:26px 0 60px; }}
  section {{ background:var(--surface); border:1px solid var(--border); border-radius:16px; padding:22px; margin-bottom:22px; }}
  h2 {{ margin:0 0 4px; font-size:19px; }}
  h2 + p.sub {{ margin:0 0 16px; color:var(--text-2); font-size:13.5px; }}
  .grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(250px,1fr)); gap:14px; }}
  .card {{ background:var(--surface-2); border:1px solid var(--border); border-radius:12px; padding:14px 16px; }}
  .card h3 {{ margin:0 0 6px; font-size:15px; color:var(--primary-dark); }}
  .card p {{ margin:0; font-size:13px; color:var(--text-2); }}
  code {{ background:var(--primary-soft); border:1px solid #dbe6ff; border-radius:6px; padding:1px 6px; font-family:Consolas,monospace; font-size:12.5px; direction:ltr; display:inline-block; }}
  table {{ width:100%; border-collapse:collapse; font-size:13.5px; }}
  th, td {{ text-align:right; padding:10px 12px; border-bottom:1px solid var(--border); }}
  th {{ background:var(--surface-2); font-size:13px; color:var(--text-2); }}
  .shot {{ margin:0 0 18px; border:1px solid var(--border); border-radius:14px; overflow:hidden; background:var(--surface); }}
  .shot figcaption {{ display:flex; flex-direction:column; gap:2px; padding:12px 16px; }}
  .shot figcaption b {{ color:var(--primary-dark); font-size:15px; }}
  .shot figcaption span {{ color:var(--text-2); font-size:12.5px; }}
  .shot img {{ display:block; width:100%; height:auto; border-top:1px solid var(--border); }}
  .step {{ border-right:3px solid var(--primary); background:var(--surface-2); border-radius:10px; padding:12px 16px; margin-bottom:12px; }}
  .step b {{ font-size:14.5px; }}
  .step p {{ margin:4px 0 0; font-size:13px; color:var(--text-2); }}
  footer {{ text-align:center; color:var(--text-2); font-size:12.5px; padding:18px 0 40px; }}
  .links a {{ color:var(--primary-dark); text-decoration:none; border-bottom:1px dashed var(--primary); margin:0 6px; }}
</style>
</head>
<body>
<header>
  <div class="wrap">
    <h1>تولید انبوه تصویر از قالب فتوشاپ</h1>
    <p>یک فایل فتوشاپ + یک فایل اکسل → برای هر ردیف یک خروجی (PNG/JPG/WEBP/PDF)، با نام‌گذاری دلخواه و پوشه‌ی جدا برای هر شیت.</p>
    <div class="badges">
      <span class="badge">Python 3.9+</span>
      <span class="badge">رابط HTML فارسی و راست‌چین</span>
      <span class="badge">نسخه‌ی ویندوزی بدون پنجره‌ی CMD</span>
      <span class="badge">MIT License</span>
    </div>
  </div>
</header>

<main class="wrap">
  <section>
    <h2>این برنامه چه می‌کند؟</h2>
    <p class="sub">برنامه‌ای کاملاً محلی (بدون اینترنت) برای کارت ویزیت، برچسب محصول، سربرگ، گواهی و هر قالبی که متن‌هایش عوض می‌شود.</p>
    <div class="grid">
{features}
    </div>
  </section>

  <section>
    <h2>خروجی PDF — هم یکپارچه، هم جدا جدا</h2>
    <p class="sub">در تب ۱ فرمت خروجی را PDF بگذارید و حالت دلخواه را انتخاب کنید.</p>
    <table>
      <thead><tr><th>حالت</th><th>خروجی</th></tr></thead>
      <tbody>
{pdf_rows}
      </tbody>
    </table>
  </section>

  <section>
    <h2>اجرا و ساخت نسخه‌ی ویندوزی</h2>
    <p class="sub">همه‌ی راه‌ها بدون پنجره‌ی کنسول (CMD) اجرا می‌شوند و آیکون اختصاصی دارند.</p>
{run_rows}
  </section>

  <section>
    <h2>نمای برنامه</h2>
    <p class="sub">اسکرین‌شات‌های واقعی از اجرای برنامه روی فایل‌های نمونه (۲ شیت، ۷ ردیف، ۰ خطا).</p>
{chr(10).join(cards)}
  </section>
</main>

<footer>
  <div class="links">
    <a href="../README.md">README</a>
    <a href="BUILD-WINDOWS.md">راهنمای ساخت exe</a>
    <a href="HANDOFF.md">راهنمای تحویل به برنامه‌نویس</a>
    <a href="README.en.md">English</a>
  </div>
  <p>MIT License — این صفحه یک فایل مستقل HTML است و آفلاین هم درست نمایش داده می‌شود.</p>
</footer>
</body>
</html>
"""
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    TARGET.write_text(html, encoding="utf-8")
    print("ساخته شد:", TARGET.relative_to(BASE), round(TARGET.stat().st_size / 1024), "KB")


if __name__ == "__main__":
    main()
