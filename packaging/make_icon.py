#!/usr/bin/env python3
"""
ساخت آیکون برنامه (packaging/icon.ico و packaging/icon.png).

اجرا:  python3 packaging/make_icon.py
نیاز:  pillow  (نصب: pip install pillow)
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

HERE = Path(__file__).resolve().parent
SIZES = [16, 24, 32, 48, 64, 128, 256]
MASTER = 1024

BLUE_TOP = (59, 130, 246)     # #3b82f6
BLUE_BOTTOM = (29, 78, 216)   # #1d4ed8
WHITE = (255, 255, 255, 255)
ACCENT = (37, 99, 235, 255)   # #2563eb
ACCENT_SOFT = (147, 197, 253, 255)


def rounded_gradient(size: int, radius_ratio: float = 0.22) -> Image.Image:
    """پس‌زمینه‌ی گرادیانی آبی با گوشه‌های گرد."""
    base = Image.new("RGBA", (size, size), BLUE_BOTTOM + (255,))
    gradient = Image.new("RGBA", (1, size))
    for y in range(size):
        t = y / max(1, size - 1)
        gradient.putpixel(
            (0, y),
            (
                round(BLUE_TOP[0] + (BLUE_BOTTOM[0] - BLUE_TOP[0]) * t),
                round(BLUE_TOP[1] + (BLUE_BOTTOM[1] - BLUE_TOP[1]) * t),
                round(BLUE_TOP[2] + (BLUE_BOTTOM[2] - BLUE_TOP[2]) * t),
                255,
            ),
        )
    base = gradient.resize((size, size))

    mask = Image.new("L", (size * 4, size * 4), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        (0, 0, size * 4 - 1, size * 4 - 1), radius=int(size * 4 * radius_ratio), fill=255
    )
    mask = mask.resize((size, size), Image.LANCZOS)

    out = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    out.paste(base, (0, 0), mask)
    return out


def draw_card(icon: Image.Image) -> Image.Image:
    """یک کارت سفید با سه خط متن (نماد جایگزینی متن‌ها) روی آیکون می‌کشد."""
    size = icon.size[0]
    draw = ImageDraw.Draw(icon)

    pad = size * 0.20
    card = (pad, pad * 1.06, size - pad, size - pad * 1.06)
    radius = size * 0.075
    # سایه‌ی نرم
    shadow = Image.new("RGBA", icon.size, (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rounded_rectangle(
        (card[0], card[1] + size * 0.018, card[2], card[3] + size * 0.018),
        radius=radius,
        fill=(15, 23, 42, 90),
    )
    shadow = shadow.filter(__import__("PIL.ImageFilter", fromlist=["ImageFilter"]).GaussianBlur(size * 0.012))
    icon.alpha_composite(shadow)

    draw.rounded_rectangle(card, radius=radius, fill=WHITE)

    # سه خط متن: دوتا آبی روشن، یکی پررنگ (خطی که «جایگزین» شده)
    left = card[0] + size * 0.075
    right = card[2] - size * 0.075
    line_h = size * 0.055
    gap = size * 0.05
    top = card[1] + size * 0.10

    widths = [1.0, 0.72, 0.86]
    colors = [ACCENT_SOFT, ACCENT, ACCENT_SOFT]
    for index, (factor, color) in enumerate(zip(widths, colors)):
        y = top + index * (line_h + gap)
        x_end = left + (right - left) * factor
        draw.rounded_rectangle((left, y, x_end, y + line_h), radius=line_h / 2, fill=color)

    # نقطه‌ی «تأیید» گوشه‌ی کارت
    dot_r = size * 0.055
    cx = card[2] - size * 0.10
    cy = card[3] - size * 0.09
    draw.ellipse((cx - dot_r, cy - dot_r, cx + dot_r, cy + dot_r), fill=ACCENT)
    tick = size * 0.026
    draw.line(
        (cx - tick * 0.9, cy, cx - tick * 0.15, cy + tick * 0.75, cx + tick, cy - tick * 0.8),
        fill=WHITE,
        width=max(2, int(size * 0.016)),
        joint="curve",
    )
    return icon


def main() -> None:
    master = draw_card(rounded_gradient(MASTER))
    master.save(HERE / "icon.png")
    images = [master.resize((s, s), Image.LANCZOS) for s in SIZES]
    images[-1].save(HERE / "icon.ico", sizes=[(s, s) for s in SIZES], append_images=images[:-1])
    print("ساخته شد:", HERE / "icon.ico", "و", HERE / "icon.png")


if __name__ == "__main__":
    main()
