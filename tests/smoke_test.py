#!/usr/bin/env python3
"""
تست سریع سلامت برنامه (بدون باز کردن مرورگر).

اجرا:  python tests/smoke_test.py

این تست:
  * فایل‌های نمونه را (در صورت نبود) می‌سازد
  * اکسل را می‌خواند و پلیس‌هولدرهای PSD را پیدا می‌کند
  * یک ردیف را رندر می‌کند (پیش‌نمایش)
  * کل خروجی را در پوشه‌ی موقت می‌سازد و تعداد فایل‌ها را گزارش می‌دهد
"""

from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

FAILED = 0


def check(title: str, condition: bool, detail: str = "") -> None:
    global FAILED
    mark = "✅" if condition else "❌"
    print(f"{mark} {title}" + (f" — {detail}" if detail else ""))
    if not condition:
        FAILED += 1


def main() -> int:
    samples = BASE_DIR / "samples"
    excel = samples / "نمونه-اطلاعات.xlsx"
    psd_path = samples / "نمونه-قالب.psd"

    if not (excel.exists() and psd_path.exists()):
        print("ساخت فایل‌های نمونه…")
        import subprocess

        subprocess.run([sys.executable, str(BASE_DIR / "tools" / "make_sample.py")], check=True)

    check("فایل اکسل نمونه موجود است", excel.exists(), str(excel.name))
    check("فایل PSD نمونه موجود است", psd_path.exists(), str(psd_path.name))

    # ۱) خواندن اکسل
    from engine.excelio import read_sheets

    sheets = read_sheets(excel)
    check("خواندن شیت‌های اکسل", len(sheets) >= 2, f"{len(sheets)} شیت")
    for sheet in sheets:
        print(f"    • {sheet.name}: {sheet.row_count} ردیف، {len(sheet.columns)} ستون")

    # ۲) لایه‌های متنی و پلیس‌هولدرها
    from psd_tools import PSDImage
    from engine.runner import build_layer_index, BatchRunner, JobSettings, SheetSettings, LayerMapping
    from engine.render import RenderOptions

    layers = build_layer_index(PSDImage.open(psd_path))
    check("لایه‌های متنی پیدا شدند", len(layers) > 0, f"{len(layers)} لایه")
    tokens = sorted({t for layer in layers for t in layer["tokens"]})
    check("پلیس‌هولدرها استخراج شدند", len(tokens) > 0, "، ".join(tokens))

    # ۳) نگاشت خودکار ستون‌ها
    from engine.runner import auto_match_columns

    matched = auto_match_columns(tokens, sheets[0])
    check("تطبیق خودکار توکن↔ستون", len(matched) == len(tokens), f"{len(matched)}/{len(tokens)}")

    # ۴) رندر یک ردیف (پیش‌نمایش)
    out_dir = Path(tempfile.mkdtemp(prefix="psd_batch_test_"))
    mappings = [
        LayerMapping(layer_id=layer["id"], mode="token", tokens={t: t for t in layer["tokens"]})
        for layer in layers
    ]
    settings = JobSettings(
        excel_path=str(excel),
        psd_path=str(psd_path),
        out_dir=str(out_dir),
        sheets=[SheetSettings(name=sheets[0].name, name_column_1=sheets[0].columns[0].letter)],
        layers=mappings,
        render=RenderOptions(scale=1.0, supersample=2.0),
    )
    runner = BatchRunner(settings)
    image, report, changed, details = runner.render_single(sheets[0].name, 0)
    check("رندر پیش‌نمایش", image is not None and image.size[0] > 0, f"ابعاد {image.size}")
    check("متن‌ها جایگزین شدند", len(changed) > 0, f"{len(changed)} لایه")
    if report.warnings:
        print("    ⚠️ هشدارهای رندر:")
        for warning in report.warnings[:5]:
            print("       -", warning)

    # ۵) اجرای کامل روی همه‌ی شیت‌ها
    full_dir = out_dir / "کامل"
    settings.out_dir = str(full_dir)
    settings.sheets = [
        SheetSettings(name=sheet.name, name_column_1=sheet.columns[0].letter) for sheet in sheets
    ]
    settings.layers = mappings
    runner = BatchRunner(settings)
    result = runner.run()
    produced = list(full_dir.rglob("*.png"))
    check("اجرای کامل تولید", result["ok"] and len(produced) == result["total"],
          f"{len(produced)} فایل از {result['total']} ردیف، {result['elapsed']} ثانیه")

    # ۶) حالت‌های خروجی PDF
    pdf_dir = out_dir / "پی‌دی‌اف"
    settings.out_dir = str(pdf_dir)
    settings.image_format = "pdf"
    settings.pdf_dpi = 120
    settings.csv_index = True
    settings.layers = mappings

    # ۶/۱) «هر لیبل جدا + یک فایل کلی از همه‌ی لیبل‌ها» (پیش‌فرض برنامه)
    settings.pdf_mode = "all"
    settings.pdf_also_individual = True
    settings.pdf_all_name = "همه-برچسب‌ها"
    result_both = BatchRunner(settings).run()
    check("حالت «هر لیبل جدا + یک فایل کلی»", result_both["ok"] and result_both["errors"] == [],
          f"{result_both['done']} ردیف، {len(result_both['errors'])} خطا")

    merged_all = pdf_dir / "همه-برچسب‌ها.pdf"
    check("فایل کلی همه‌ی لیبل‌ها", merged_all.exists() and merged_all.stat().st_size > 0,
          f"{round(merged_all.stat().st_size / 1024)} KB" if merged_all.exists() else "ساخته نشد")

    sheet_pdfs = sorted(pdf_dir.glob("*/*.pdf"))
    row_pdfs = [path for path in sheet_pdfs if path.stem != path.parent.name]
    check("فایل جداگانه برای هر لیبل", len(row_pdfs) == result_both["total"],
          f"{len(row_pdfs)} فایل از {result_both['total']} ردیف")
    check("در این حالت فایل یکپارچه‌ی هر پوشه ساخته نمی‌شود",
          not [path for path in sheet_pdfs if path.stem == path.parent.name],
          "بدون فایل اضافه")
    check("فهرست CSV در پوشه‌های PDF",
          all((pdf_dir / sheet.name / "_فهرست-خروجی.csv").exists() for sheet in sheets),
          "برای همه‌ی شیت‌ها")

    try:
        from pypdf import PdfReader

        pages = len(PdfReader(str(merged_all)).pages)
        check("تعداد صفحه‌های فایل کلی", pages == result_both["total"], f"{pages} صفحه")
    except ImportError:
        print("    ℹ️ pypdf نصب نیست؛ بررسی تعداد صفحه‌ها رد شد (pip install pypdf)")

    # ۶/۲) حالت «در هر پوشه یک فایل یکپارچه»
    sheet_dir = out_dir / "پی‌دی‌اف-هر-پوشه"
    settings.out_dir = str(sheet_dir)
    settings.pdf_mode = "sheet"
    settings.pdf_also_individual = False
    runner_sheet = BatchRunner(settings).run()
    per_sheet = sorted(path for path in sheet_dir.glob("*/*.pdf") if path.stem == path.parent.name)
    check("حالت «در هر پوشه یک فایل یکپارچه»", runner_sheet["ok"] and len(per_sheet) == len(sheets),
          "، ".join(f"{path.parent.name}: {path.name}" for path in per_sheet))

    try:
        from pypdf import PdfReader

        counts = {path.parent.name: len(PdfReader(str(path)).pages) for path in per_sheet}
        check("صفحه‌های PDF هر پوشه", all(counts[sheet.name] == sheet.row_count for sheet in sheets),
              "، ".join(f"{name}: {count}" for name, count in counts.items()))
    except ImportError:
        pass

    # ۶/۳) حالت «فقط هر لیبل جداگانه»
    each_dir = out_dir / "پی‌دی‌اف-جدا"
    settings.out_dir = str(each_dir)
    settings.pdf_mode = "each"
    runner_each = BatchRunner(settings).run()
    each_files = sorted(each_dir.glob("*/*.pdf"))
    check("حالت «فقط هر لیبل جداگانه»", len(each_files) == runner_each["total"] and not (each_dir / "همه-برچسب‌ها.pdf").exists(),
          f"{len(each_files)} فایل از {runner_each['total']} ردیف")

    settings.image_format = "png"
    settings.pdf_mode = "all"
    settings.pdf_also_individual = True

    print("\nپوشه‌ی خروجی تست:", out_dir)
    shutil.rmtree(out_dir, ignore_errors=True)

    print("\n" + ("=" * 50))
    if FAILED:
        print(f"❌ {FAILED} مورد ناموفق بود.")
        return 1
    print("✅ همه‌ی تست‌ها موفق بودند. برنامه آماده است.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
