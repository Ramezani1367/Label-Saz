"""
ساخت فایل‌های نمونه (PSD + اکسل) برای آزمایش برنامه.

اجرا:  python tools/make_sample.py
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter
from psd_tools import PSDImage
from psd_tools.api.layers import TypeLayer

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from engine import textdata  # noqa: E402
from openpyxl import Workbook  # noqa: E402
from openpyxl.styles import Font, PatternFill  # noqa: E402

SAMPLES = BASE_DIR / "samples"
TEMPLATE_PSD = Path(__file__).resolve().parent / "assets" / "text_template.psd"
W, H = 1240, 700


# --------------------------------------------------------------- پس‌زمینه


def make_background(width: int = W, height: int = H) -> Image.Image:
    x = np.linspace(0, 1, width)[None, :]
    y = np.linspace(0, 1, height)[:, None]
    r = (12 + 40 * x + 25 * y).clip(0, 255)
    g = (26 + 70 * x + 45 * y).clip(0, 255)
    b = (44 + 110 * x + 80 * y).clip(0, 255)
    image = Image.fromarray(np.dstack([r, g, b]).astype(np.uint8), "RGB")

    draw = ImageDraw.Draw(image, "RGBA")
    for i in range(14):
        cx = int(width * (0.08 + 0.07 * i))
        cy = int(height * (0.2 + 0.06 * (i % 5)))
        radius = 90 + 18 * (i % 4)
        draw.ellipse([cx - radius, cy - radius, cx + radius, cy + radius], fill=(80, 190, 255, 12))
    image = image.filter(ImageFilter.GaussianBlur(2))

    draw = ImageDraw.Draw(image, "RGBA")
    draw.rounded_rectangle([70, 120, W - 70, H - 120], radius=28, fill=(9, 16, 26, 190), outline=(120, 200, 255, 90), width=2)
    draw.rectangle([70, 120, 82, H - 120], fill=(55, 177, 255, 230))
    return image


# -------------------------------------------------- کپی لایه‌ی متنی


def clone_type_layer(source_psd: PSDImage, layer) -> TypeLayer:
    record = copy.deepcopy(layer._record)
    channels = copy.deepcopy(layer._channels)
    clone = TypeLayer(source_psd, record, channels)
    return clone


def position_layer(layer, x: float, y: float, justify: int = 1) -> None:
    """
    جابجایی لایه‌ی متنی.
    x,y = نقطه‌ی مبدأ (برای تراز راست، لبه‌ی راست متن).
    """
    data = layer._data
    transform = list(data.transform)
    transform[4] = float(x)
    transform[5] = float(y)
    data.transform = tuple(transform)  # type: ignore[assignment]
    try:
        from psd_tools.psd.engine_data import Integer

        engine = layer.engine_dict
        for run in engine["ParagraphRun"]["RunArray"]:
            props = run["ParagraphSheet"]["Properties"]
            if "Justification" in props:
                props["Justification"].value = int(justify)
            else:
                props["Justification"] = Integer(int(justify))
    except Exception as exc:
        print("هشدار: تنظیم تراز ناموفق بود:", exc)
    try:
        # یک جعبه‌ی کوچک دور نقطه‌ی مبدأ: برنامه از لبه‌ی این جعبه برای تراز متن استفاده می‌کند
        offset = 3 if justify else -3
        layer._record.left = int(round(x)) - 3
        layer._record.top = int(round(y)) - 20
        layer._record.right = int(round(x)) + 3
        layer._record.bottom = int(round(y)) + 20
    except Exception:
        pass


def build_sample_psd(template: Path, target: Path) -> Path:
    if not template.exists():
        raise SystemExit(
            "فایل قالب پایه پیدا نشد. برای ساخت نمونه به فایل tests/psd_files/text.psd نیاز است."
        )
    base = PSDImage.open(template)
    text_layers = [l for l in base.descendants() if l.kind == "type"]
    if not text_layers:
        raise SystemExit("قالب پایه لایه‌ی متنی ندارد.")
    donor = text_layers[0]

    # سند پایه: فقط لایه‌ی متنی اهداکننده را نگه می‌داریم و بقیه حذف می‌شوند
    for layer in list(base):
        if layer is not donor:
            base.remove(layer)

    # اندازه‌ی سند را به اندازه‌ی طرح تغییر می‌دهیم
    try:
        header = base._record.header
        header.width = W
        header.height = H
    except Exception as exc:
        print("هشدار: تغییر اندازه‌ی سند ناموفق بود:", exc)

    background = make_background()
    bg_layer = base.create_pixel_layer(background.convert("RGB"), name="background")
    bg_layer.name = "پس‌زمینه"
    base.remove(bg_layer)
    base.insert(0, bg_layer)

    right_edge = 900
    specs = [
        ("{{نام و نام خانوادگی}}", right_edge, 250, 0),
        ("{{سمت}}", right_edge, 300, 0),
        ("{{شرکت}}", right_edge, 350, 0),
        ("{{موبایل}} | {{ایمیل}}", right_edge, 420, 0),
        ("{{سایت}}", right_edge, 470, 1),
    ]

    donor_text_set = False
    for index, (text, x, y, justify) in enumerate(specs):
        if index == 0:
            layer = donor
        else:
            layer = clone_type_layer(base, donor)
            base.append(layer)
        textdata.set_layer_text(layer, text)
        layer.name = f"متن {index + 1}"
        position_layer(layer, x, y, justify)
        donor_text_set = True

    target.parent.mkdir(parents=True, exist_ok=True)
    base.save(str(target), encoding="utf-8")
    return target


def build_sample_excel(target: Path) -> Path:
    wb = Workbook()
    sheet = wb.active
    sheet.title = "کارت ویزیت"
    sheet.sheet_view.rightToLeft = True
    headers = ["نام و نام خانوادگی", "سمت", "شرکت", "موبایل", "ایمیل", "سایت"]
    rows = [
        ["سارا محمدی", "مدیر فروش", "شرکت آریا سیستم", "۰۹۱۲۳۴۵۶۷۸۹", "sara@arya.ir", "arya.ir"],
        ["علی رضایی", "کارشناس بازاریابی", "گروه نوآوران شرق", "۰۹۳۵۱۱۱۲۲۳۳", "ali@noavaran.ir", "noavaran.ir"],
        ["مریم کاظمی", "مدیرعامل", "استودیو رها", "۰۹۱۹۸۸۷۷۶۶۵", "maryam@raha.studio", "raha.studio"],
        ["حسین کریمی", "حسابدار", "شرکت پویا تجارت", "۰۹۰۲۳۳۳۴۴۵۵", "hossein@pooya.co", "pooya.co"],
    ]
    fill = PatternFill("solid", fgColor="1E3A5F")
    for col, title in enumerate(headers, start=1):
        cell = sheet.cell(row=1, column=col, value=title)
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = fill
    for r, row in enumerate(rows, start=2):
        for c, value in enumerate(row, start=1):
            sheet.cell(row=r, column=c, value=value)
    for col in range(1, len(headers) + 1):
        sheet.column_dimensions[chr(64 + col)].width = 24
    sheet.freeze_panes = "A2"

    sheet2 = wb.create_sheet("برچسب محصول")
    sheet2.sheet_view.rightToLeft = True
    headers2 = ["نام محصول", "کد محصول", "قیمت", "موبایل", "سمت", "شرکت", "ایمیل", "سایت", "نام و نام خانوادگی"]
    rows2 = [
        ["روغن زیتون فرابکر", "OL-1001", "۴۵۰٫۰۰۰", "۰۹۱۲۳۴۵۶۷۸۹", "فروشگاه مرکزی", "آریا سیستم", "-", "-", "-"],
        ["عسل طبیعی کوهستان", "HO-2043", "۸۹۰٫۰۰۰", "۰۹۳۵۱۱۱۲۲۳۳", "واحد فروش", "نوآوران شرق", "-", "-", "-"],
        ["زعفران سرگل", "SF-3310", "۱٫۲۵۰٫۰۰۰", "۰۹۱۹۸۸۷۷۶۶۵", "پخش عمده", "رها", "-", "-", "-"],
    ]
    for col, title in enumerate(headers2, start=1):
        cell = sheet2.cell(row=1, column=col, value=title)
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="2F5D3A")
    for r, row in enumerate(rows2, start=2):
        for c, value in enumerate(row, start=1):
            sheet2.cell(row=r, column=c, value=value)
    for col in range(1, len(headers2) + 1):
        sheet2.column_dimensions[chr(64 + col)].width = 22

    target.parent.mkdir(parents=True, exist_ok=True)
    wb.save(str(target))
    return target


def main() -> None:
    SAMPLES.mkdir(parents=True, exist_ok=True)
    psd = build_sample_psd(TEMPLATE_PSD, SAMPLES / "نمونه-قالب.psd")
    xlsx = build_sample_excel(SAMPLES / "نمونه-اطلاعات.xlsx")
    print("ساخته شد:", psd)
    print("ساخته شد:", xlsx)


if __name__ == "__main__":
    main()
