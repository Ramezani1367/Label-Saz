"""
رندر فایل فتوشاپ به تصویر (PNG/JPG) با متن‌های جایگزین‌شده.

روش کار:
  1) همه‌ی لایه‌های غیرمتنی با موتور psd-tools ترکیب می‌شوند (حالت «پی‌اس‌دی بدون متن»).
  2) متن هر لایه‌ی متنی با فونت واقعی و با پشتیبانی فارسی/عربی (HarfBuzz) مجدداً کشیده می‌شود.
  3) نتیجه روی هم ترکیب و خروجی گرفته می‌شود.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

import numpy as np
from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont, features

from . import textdata
from .fonts import FontEntry, library

# ------------------------------------------------------------------ تنظیمات


@dataclass
class RenderOptions:
    scale: float = 1.0                # مقیاس خروجی نسبت به سند
    supersample: float = 2.0          # سوپرسمپل برای نرم‌تر شدن لبه‌ها
    font_scale: float = 1.0           # ضریب اندازه‌ی فونت
    line_height: float = 1.0          # ضریب فاصله‌ی خطوط
    offset_x: float = 0.0             # جابجایی افقی متن (پیکسل سند)
    offset_y: float = 0.0             # جابجایی عمودی متن (پیکسل سند)
    font_override: str | None = None  # مسیر فایل فونت یا نام خانواده
    transparent: bool = False         # پس‌زمینه شفاف
    background: str | None = None     # رنگ پس‌زمینه (مثل #ffffff)
    ignore_effects: bool = False      # نادیده گرفتن افکت‌های لایه
    text_color: str | None = None     # رنگ اجباری متن (مثل #ffffff)
    anchor_mode: str = "box"          # box = لبه‌ی جعبه‌ی متن اصلی | origin = نقطه‌ی مبدأ فتوشاپ
    wrap_text: bool = True            # شکستن خطوط بلند در متن‌های پاراگرافی


@dataclass
class LayerReport:
    layer: str
    text: str
    font_used: str | None = None
    font_missing: bool = False
    warnings: list[str] = field(default_factory=list)


@dataclass
class RenderReport:
    layers: list[LayerReport] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


# ------------------------------------------------------------ استایل متن


@dataclass
class TextStyle:
    family: str = "Arial"
    size: float = 16.0
    color: tuple[int, int, int] = (0, 0, 0)
    alpha: float = 1.0
    bold: bool = False
    italic: bool = False
    tracking: float = 0.0
    leading: float = 0.0
    auto_leading: bool = True
    underline: bool = False
    strikethrough: bool = False
    stroke_color: tuple[int, int, int] | None = None
    stroke_width: float = 0.0
    justify: int = 0  # 0=شروع 1=پایان 2=وسط 3=دوطرفه


def _num(value: Any, default: float) -> float:
    try:
        if hasattr(value, "value"):
            value = value.value
        return float(value)
    except Exception:
        return default


def _color(value: Any, default: tuple[int, int, int] = (0, 0, 0)) -> tuple[tuple[int, int, int], float]:
    """رنگ engine data فتوشاپ = [آلفا, r, g, b] با بازه‌ی ۰..۱"""
    try:
        values = value["Values"] if "Values" in value else value
        numbers = [_num(v, 0.0) for v in values]
    except Exception:
        return default, 1.0
    if len(numbers) >= 4:
        alpha, r, g, b = numbers[0], numbers[1], numbers[2], numbers[3]
    elif len(numbers) == 3:
        alpha, (r, g, b) = 1.0, tuple(numbers)  # type: ignore[assignment]
    else:
        return default, 1.0
    clamp = lambda x: max(0, min(255, int(round(x * 255))))  # noqa: E731
    return (clamp(r), clamp(g), clamp(b)), max(0.0, min(1.0, alpha))


def parse_style(layer: Any) -> TextStyle:
    style = TextStyle()
    try:
        engine = layer.engine_dict
        runs = engine["StyleRun"]["RunArray"]
        data = runs[0]["StyleSheet"]["StyleSheetData"] if len(runs) else None
        if data is not None:
            try:
                family = layer.resource_dict["FontSet"][data["Font"].value]["Name"].value
                style.family = str(family)
            except Exception:
                pass
            style.size = _num(data.get("FontSize"), 16.0)
            if "FillColor" in data:
                style.color, style.alpha = _color(data["FillColor"])
            style.bold = bool(_num(data.get("FauxBold"), 0))
            style.italic = bool(_num(data.get("FauxItalic"), 0))
            style.tracking = _num(data.get("Tracking"), 0.0)
            style.leading = _num(data.get("Leading"), 0.0)
            style.auto_leading = bool(_num(data.get("AutoLeading"), 1))
            style.underline = bool(_num(data.get("Underline"), 0))
            style.strikethrough = bool(_num(data.get("Strikethrough"), 0))
            if bool(_num(data.get("StrokeFlag"), 0)) and "StrokeColor" in data:
                style.stroke_color, _ = _color(data["StrokeColor"])
                style.stroke_width = _num(data.get("OutlineWidth"), 1.0)
        try:
            props = engine["ParagraphRun"]["RunArray"][0]["ParagraphSheet"]["Properties"]
            style.justify = int(_num(props.get("Justification"), 0))
        except Exception:
            style.justify = 0
    except Exception:
        pass
    return style


# -------------------------------------------------------------- افکت‌ها


def _descriptor(effect: Any):
    """دسترسی به دیکشنری خام افکت (با سازگاری نسخه‌های مختلف psd-tools)."""
    for attribute in ("descriptor", "value"):
        try:
            data = getattr(effect, attribute)
        except Exception:
            continue
        if data is not None and hasattr(data, "get"):
            return data
    return None


def _descriptor_number(descriptor: Any, key: bytes, default: float) -> float:
    if descriptor is None:
        return default
    try:
        if key in descriptor:
            return float(getattr(descriptor[key], "value", descriptor[key]))
    except Exception:
        pass
    return default


def _descriptor_color(descriptor: Any, key: bytes = b"Clr ") -> tuple[int, int, int] | None:
    """رنگ افکت: دیکشنری با کلیدهای Rd  / Grn / Bl  (۰ تا ۲۵۵)."""
    if descriptor is None:
        return None
    try:
        if key not in descriptor:
            return None
        color = descriptor[key]
        if not hasattr(color, "get"):
            return None
        values = []
        for channel in (b"Rd  ", b"Grn ", b"Bl  "):
            if channel in color:
                value = float(getattr(color[channel], "value", color[channel]))
                values.append(max(0, min(255, int(round(value)))))
        if len(values) == 3:
            return (values[0], values[1], values[2])
    except Exception:
        pass
    return None


import weakref

_effect_cache: "weakref.WeakKeyDictionary[Any, dict]" = weakref.WeakKeyDictionary()


def layer_effects_info(layer: Any) -> dict:
    """
    اطلاعات افکت‌های لایه: سایه‌ی بیرونی، خط دور، رنگ رویی، درخشش.
    (فقط افکت‌های فعال در نظر گرفته می‌شوند.)
    """
    try:
        cached = _effect_cache.get(layer)
    except TypeError:  # لایه قابل نگه‌داشتن با weakref نیست
        cached = None
    if cached is not None:
        return cached

    info: dict = {"shadow": None, "stroke": None, "overlay": None, "glow": None, "names": []}
    try:
        effects = layer.effects
    except Exception:
        effects = None

    if effects is not None:
        try:
            for effect in effects:
                name = type(effect).__name__
                try:
                    if not getattr(effect, "enabled", True):
                        continue
                except Exception:
                    pass
                descriptor = _descriptor(effect)
                if descriptor is None:
                    continue
                info["names"].append(name)
                opacity = _descriptor_number(descriptor, b"Opct", 100.0) / 100.0
                blur = _descriptor_number(descriptor, b"blur", 0.0)

                if name == "DropShadow":
                    info["shadow"] = {
                        "color": _descriptor_color(descriptor) or (0, 0, 0),
                        "opacity": max(0.0, min(1.0, opacity)),
                        "distance": _descriptor_number(descriptor, b"Dstn", 0.0),
                        "angle": _descriptor_number(descriptor, b"lagl", 120.0),
                        "size": blur,
                        "choke": _descriptor_number(descriptor, b"Ckmt", 0.0),
                    }
                elif name == "Stroke":
                    info["stroke"] = {
                        "color": _descriptor_color(descriptor) or (0, 0, 0),
                        "opacity": max(0.0, min(1.0, opacity)),
                        "size": _descriptor_number(descriptor, b"Sz  ", 1.0),
                        "position": _stroke_position(descriptor),
                    }
                elif name == "ColorOverlay":
                    info["overlay"] = {
                        "color": _descriptor_color(descriptor) or (0, 0, 0),
                        "opacity": max(0.0, min(1.0, opacity)),
                    }
                elif name == "OuterGlow":
                    info["glow"] = {
                        "color": _descriptor_color(descriptor) or (255, 255, 0),
                        "opacity": max(0.0, min(1.0, opacity)),
                        "size": max(blur, _descriptor_number(descriptor, b"Ckmt", 0.0)),
                    }
        except Exception:
            pass

    try:
        _effect_cache[layer] = info
    except TypeError:
        pass
    return info


def _stroke_position(descriptor: Any) -> str:
    try:
        style = descriptor[b"Styl"]
        value = getattr(style, "enum", None) or getattr(style, "value", b"")
        if isinstance(value, bytes):
            value = value.decode("ascii", "ignore")
        value = str(value).lower()
        if "out" in value:
            return "outside"
        if "ins" in value:
            return "inside"
        return "center"
    except Exception:
        return "outside"


# ------------------------------------------------------------- ترکیب لایه


_BLEND_FUNCS = {
    "multiply": ImageChops.multiply,
    "screen": ImageChops.screen,
    "darken": ImageChops.darker,
    "lighten": ImageChops.lighter,
    "difference": ImageChops.difference,
}


def _blend_mode_name(layer: Any) -> str:
    try:
        mode = layer.blend_mode
        return str(getattr(mode, "name", mode) or "NORMAL").lower()
    except Exception:
        return "normal"


def composite_layer(
    canvas: Image.Image,
    layer_img: Image.Image,
    opacity: float = 1.0,
    blend_mode: str = "normal",
    position: tuple[int, int] = (0, 0),
) -> Image.Image:
    """ترکیب لایه‌ی متنی روی تصویر اصلی با احترام به شفافیت و حالت ترکیب."""
    if layer_img.width == 0 or layer_img.height == 0:
        return canvas

    if opacity <= 0.001:
        return canvas

    base = np.asarray(canvas.convert("RGBA"), dtype=np.float32) / 255.0
    x, y = position
    h, w = layer_img.height, layer_img.width
    ph, pw = canvas.height, canvas.width

    # برش ناحیه‌ی هدف
    x0, y0 = max(0, x), max(0, y)
    x1, y1 = min(pw, x + w), min(ph, y + h)
    if x1 <= x0 or y1 <= y0:
        return canvas

    sx0, sy0 = x0 - x, y0 - y
    lw, lh = x1 - x0, y1 - y0
    patch = layer_img.crop((sx0, sy0, sx0 + lw, sy0 + lh))
    top = np.asarray(patch, dtype=np.float32) / 255.0
    top_alpha = top[..., 3:4] * float(opacity)
    dst = base[y0:y1, x0:x1]

    if blend_mode in _BLEND_FUNCS or blend_mode in {"overlay", "softlight", "hardlight"}:
        top_img = patch.convert("RGB")
        dst_img = canvas.convert("RGB").crop((x0, y0, x1, y1))
        func = _BLEND_FUNCS.get(blend_mode)
        if func is not None:
            blended = func(dst_img, top_img)
        elif blend_mode == "overlay":
            blended = Image.blend(dst_img, ImageChops.screen(dst_img, top_img), 0.5)
        elif blend_mode == "hardlight":
            blended = Image.blend(dst_img, ImageChops.multiply(dst_img, top_img), 0.5)
        else:  # softlight (تقریبی)
            blended = Image.blend(dst_img, ImageChops.screen(dst_img, top_img), 0.25)
        top_rgb = np.asarray(blended, dtype=np.float32) / 255.0
    else:
        top_rgb = top[..., :3]

    out_rgb = dst[..., :3] * (1 - top_alpha) + top_rgb * top_alpha
    out_a = dst[..., 3:4] + top_alpha * (1 - dst[..., 3:4])
    dst[..., :3] = out_rgb
    dst[..., 3:4] = out_a

    return Image.fromarray((base * 255.0).astype(np.uint8), "RGBA")


# ------------------------------------------------------------------ رندر


class PsdRenderer:
    """رندر یک سند PSD به تصویر با امکان جایگزینی متن لایه‌ها."""

    def __init__(self, options: RenderOptions | None = None):
        self.options = options or RenderOptions()
        self.fonts = library()
        self.fonts.load()

    # ---------------------------------------------------------- کمکی‌ها
    @staticmethod
    def _transform_scale(layer: Any) -> tuple[float, float]:
        try:
            xx, xy, yx, yy, _tx, _ty = layer.transform
            sx = math.hypot(float(xx), float(yx)) or 1.0
            sy = math.hypot(float(xy), float(yy)) or 1.0
            return sx, sy
        except Exception:
            return 1.0, 1.0

    def _font_entry(self, style: TextStyle, rtl: bool, text: str) -> tuple[FontEntry | None, bool]:
        base_family, name_bold, name_italic = _family_and_style(style.family)
        entry = self.fonts.resolve(
            style.family,
            rtl=rtl,
            override=self.options.font_override,
            bold=name_bold,
            italic=name_italic,
            sample_text=text,
        )
        missing = not self.fonts.text_supported(entry, text)
        return entry, missing

    # ------------------------------------------------------------ رندر
    def render(
        self,
        psd: Any,
        report: RenderReport | None = None,
        layer_options: dict[int, dict] | None = None,
    ) -> Image.Image:
        opts = self.options
        report = report if report is not None else RenderReport()
        scale = max(0.05, float(opts.scale))
        out_size = (max(1, int(round(psd.width * scale))), max(1, int(round(psd.height * scale))))

        # ۱) پس‌زمینه: همه‌ی لایه‌های غیرمتنی
        try:
            base = psd.composite(
                layer_filter=lambda layer: not textdata.is_text_layer(layer),
                color=None,
                alpha=0.0,
            )
        except Exception as exc:  # pragma: no cover
            report.warnings.append(f"ترکیب لایه‌های غیرمتنی انجام نشد: {exc}")
            base = Image.new("RGBA", (psd.width, psd.height), (255, 255, 255, 0))
        base = base.convert("RGBA")
        if base.size != out_size:
            base = base.resize(out_size, Image.LANCZOS)

        if opts.transparent:
            canvas = base
        else:
            background = (255, 255, 255, 255)
            if opts.background:
                background = _hex_to_rgba(opts.background)
            elif getattr(psd, "has_background", False):
                try:
                    bg = psd.background_color
                    background = (int(bg[0]), int(bg[1]), int(bg[2]), 255)
                except Exception:
                    pass
            canvas = Image.new("RGBA", out_size, background)
            canvas.alpha_composite(base)
            canvas = canvas.convert("RGBA")

        # ۲) لایه‌های متنی به ترتیب پایین به بالا
        layers = [l for l in textdata.iter_text_layers(psd, include_hidden=False)]
        options_map = layer_options or {}
        for index, layer in reversed(list(enumerate(layers))):
            try:
                canvas = self._render_text_layer(canvas, layer, report, options_map.get(index))
            except Exception as exc:  # pragma: no cover
                name = textdata.layer_display_name(layer)
                report.warnings.append(f"کشیدن متن لایه «{name}» انجام نشد: {exc}")
        return canvas

    # -------------------------------------------------------- یک لایه متن
    def _render_text_layer(
        self,
        canvas: Image.Image,
        layer: Any,
        report: RenderReport,
        options: dict | None = None,
    ) -> Image.Image:
        opts = self.options
        text = textdata.to_plain(layer.text).rstrip("\n")
        name = textdata.layer_display_name(layer)
        entry_report = LayerReport(layer=name, text=text[:200])
        report.layers.append(entry_report)

        if not text.strip():
            return canvas

        style = parse_style(layer)
        options = options or {}
        forced_direction = options.get("direction", "auto")
        if forced_direction == "rtl":
            rtl = True
        elif forced_direction == "ltr":
            rtl = False
        else:
            rtl = textdata.first_strong_is_rtl(text)
        entry, missing = self._font_entry(style, rtl, text)
        entry_report.font_used = f"{entry.family} ({entry.path})" if entry else None
        entry_report.font_missing = missing
        if missing:
            entry_report.warnings.append(f"فونت مناسب برای «{style.family}» پیدا نشد؛ فونت جانشین استفاده شد.")
            report.warnings.append(f"لایه «{name}»: فونت «{style.family}» روی سیستم نیست.")

        effects = {} if opts.ignore_effects else layer_effects_info(layer)
        if effects.get("names"):
            unsupported = [n for n in effects["names"] if n not in {"DropShadow", "Stroke", "ColorOverlay", "OuterGlow"}]
            if unsupported:
                report.warnings.append(f"لایه «{name}»: افکت‌های {', '.join(unsupported)} بازسازی نشدند.")

        fill = style.color
        if opts.text_color:
            forced = _hex_to_rgba(opts.text_color)
            fill = (forced[0], forced[1], forced[2])
        if effects.get("overlay"):
            overlay = effects["overlay"]
            alpha = overlay["opacity"]
            fill = tuple(
                int(round(fill[i] * (1 - alpha) + overlay["color"][i] * alpha)) for i in range(3)
            )

        try:
            alpha_layer = layer.opacity / 255.0
        except Exception:
            alpha_layer = 1.0
        alpha_layer *= style.alpha

        # مقیاس و مرجع
        s_doc = float(opts.scale)
        sx, sy = self._transform_scale(layer)
        s = max(0.05, (sx + sy) / 2) * s_doc
        font_px = max(2.0, style.size * s * opts.font_scale)

        family_base, name_bold, name_italic = _family_and_style(style.family)
        faux_bold = bool(style.bold) and not name_bold
        font_ss = self.fonts.load_font(entry, font_px * opts.supersample, name_bold, name_italic)
        can_shape = features.check("raqm") and isinstance(font_ss, ImageFont.FreeTypeFont)
        ascent, descent = font_ss.getmetrics()
        if style.auto_leading or style.leading <= 0.01:
            advance = float(ascent + descent) * opts.line_height
        else:
            advance = style.leading * s * opts.font_scale * opts.supersample * opts.line_height

        try:
            xx, xy, yx, yy, tx, ty = layer.transform
            _ = (xx, xy, yx, yy)
        except Exception:
            tx, ty = layer.bbox[0], layer.bbox[1]

        origin_x = (float(tx) + float(opts.offset_x)) * s_doc
        origin_y = (float(ty) + float(opts.offset_y)) * s_doc

        lines = text.split("\n")
        direction = "rtl" if rtl else "ltr"
        measure = ImageDraw.Draw(Image.new("L", (1, 1)))

        # متن‌های پاراگرافی: شکستن خطوط بر اساس عرض قاب
        wrap_width = None
        if opts.wrap_text:
            try:
                if getattr(layer, "text_type", None) is not None and str(layer.text_type) == "TextType.PARAGRAPH":
                    frame_width = float(layer.bbox[2] - layer.bbox[0]) * s
                    if frame_width > 40:
                        wrap_width = frame_width
            except Exception:
                wrap_width = None

        def line_width(value: str) -> float:
            if can_shape:
                try:
                    return float(measure.textlength(value, font=font_ss, direction=direction))
                except Exception:
                    pass
            try:
                return float(font_ss.getlength(value))
            except Exception:
                return float(measure.textlength(value, font=font_ss))

        if wrap_width:
            lines = _wrap_lines(lines, line_width, wrap_width * opts.supersample, rtl)

        widths = [line_width(line) for line in lines]
        max_width = max(widths) if widths else 0.0

        # عرض جعبه‌ی متن (برای متن پاراگرافی از عرض لایه استفاده می‌کنیم)
        box_width = max_width
        try:
            if getattr(layer, "text_type", None) is not None and str(layer.text_type) == "TextType.PARAGRAPH":
                box_width = max(max_width, (layer.bbox[2] - layer.bbox[0]) * s)
        except Exception:
            pass
        box_width = max(box_width, 1.0)

        # ---- لنگر افقی متن -------------------------------------------------
        # حالت «جعبه»: از جعبه‌ی متنِ خود فایل فتوشاپ استفاده می‌کنیم (پیش‌بینی‌پذیرترین حالت)
        # حالت «مبدأ»: نقطه‌ی مبدأ فتوشاپ + تراز پاراگراف (۹۹٪ فایل‌ها یکسان است)
        justify = style.justify
        if opts.anchor_mode == "origin":
            if rtl:
                anchor = {0: "rs", 1: "ls", 2: "ms"}.get(justify, "rs")
            else:
                anchor = {0: "ls", 1: "rs", 2: "ms"}.get(justify, "ls")
            anchor_x = origin_x
        else:
            try:
                box_left, box_right = float(layer.bbox[0]), float(layer.bbox[2])
            except Exception:
                box_left = box_right = origin_x
            if justify == 2:
                anchor = "ms"
                anchor_x = (box_left + box_right) / 2
            elif rtl:
                # پاراگراف راست‌به‌چپ: ۰=شروع(راست)، ۱=پایان(چپ)
                if justify == 1:
                    anchor, anchor_x = "ls", box_left
                else:
                    anchor, anchor_x = "rs", box_right
            else:
                # پاراگراف چپ‌به‌راست: ۰=چپ، ۱=راست
                if justify == 1:
                    anchor, anchor_x = "rs", box_right
                else:
                    anchor, anchor_x = "ls", box_left

        anchor_x += float(opts.offset_x)

        origin_ss = (origin_x * opts.supersample, origin_y * opts.supersample)
        box_ss = box_width * opts.supersample

        # ناحیه‌ی مورد نیاز
        pad = max(16.0, font_px * opts.supersample * 0.6)
        stroke_extra = 0.0
        if style.stroke_color and style.stroke_width:
            stroke_extra = style.stroke_width * s * opts.supersample
        if effects.get("stroke"):
            stroke_extra = max(stroke_extra, effects["stroke"]["size"] * s * opts.supersample)
        glow_extra = 0.0
        if effects.get("glow"):
            glow_extra = effects["glow"]["size"] * s * opts.supersample
        shadow_extra = 0.0
        if effects.get("shadow"):
            shadow_extra = effects["shadow"]["size"] * s * opts.supersample + effects["shadow"]["distance"] * s * opts.supersample
        extra = pad + stroke_extra + glow_extra + shadow_extra

        anchor_ss = anchor_x * opts.supersample
        if anchor == "ls":
            left, right = anchor_ss, anchor_ss + box_ss
        elif anchor == "rs":
            left, right = anchor_ss - box_ss, anchor_ss
        else:
            left, right = anchor_ss - box_ss / 2, anchor_ss + box_ss / 2
        left -= extra
        right += extra
        top = origin_ss[1] - ascent - extra
        bottom = origin_ss[1] + (len(lines) - 1) * advance + descent + extra

        x0, y0 = int(math.floor(left)), int(math.floor(top))
        w = max(1, int(math.ceil(right)) - x0)
        h = max(1, int(math.ceil(bottom)) - y0)

        region = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        draw = ImageDraw.Draw(region)

        stroke_w = 0
        stroke_fill = None
        if style.stroke_color and style.stroke_width:
            stroke_w = max(1, int(round(style.stroke_width * s * opts.supersample)))
            stroke_fill = style.stroke_color + (255,)
        if faux_bold:
            # بولد مصنوعی فتوشاپ: ضخیم‌کردن جزئی نویسه‌ها
            faux_w = max(1, int(round(font_px * opts.supersample * 0.028)))
            if faux_w >= stroke_w:
                stroke_w = faux_w
                stroke_fill = fill + (255,)
        if effects.get("stroke"):
            eff = effects["stroke"]
            stroke_w = max(stroke_w, int(round(eff["size"] * s * opts.supersample)))
            stroke_fill = eff["color"] + (255,)

        for index, line in enumerate(lines):
            baseline = origin_ss[1] + index * advance
            x_anchor = anchor_ss

            kwargs = dict(font=font_ss, fill=fill + (255,), anchor=anchor)
            if stroke_w:
                kwargs.update(stroke_width=stroke_w, stroke_fill=stroke_fill)
            try:
                if can_shape:
                    draw.text((x_anchor - x0, baseline - y0), line, direction=direction, **kwargs)
                else:
                    draw.text((x_anchor - x0, baseline - y0), line, **kwargs)
            except Exception:
                draw.text((x_anchor - x0, baseline - y0), line, font=font_ss, fill=fill + (255,))

            if style.underline or style.strikethrough:
                width = widths[index]
                if anchor == "rs":
                    ux0 = x_anchor - width
                elif anchor == "ms":
                    ux0 = x_anchor - width / 2
                else:
                    ux0 = x_anchor
                thickness = max(1, int(round(font_px * opts.supersample * 0.07)))
                if style.underline:
                    uy = baseline + descent * 0.35
                    draw.rectangle([ux0 - x0, uy - y0, ux0 + width - x0, uy + thickness - y0], fill=fill + (255,))
                if style.strikethrough:
                    uy = baseline - ascent * 0.32
                    draw.rectangle([ux0 - x0, uy - y0, ux0 + width - x0, uy + thickness - y0], fill=fill + (255,))

        # نمونه‌برداری مجدد به مقیاس نهایی
        if opts.supersample > 1.001:
            region = region.resize(
                (max(1, int(round(w / opts.supersample))), max(1, int(round(h / opts.supersample)))),
                Image.LANCZOS,
            )
            x0 = int(round(x0 / opts.supersample))
            y0 = int(round(y0 / opts.supersample))

        # ۳) افکت‌ها
        region = self._apply_effects(region, effects, s, opacity=alpha_layer)

        return composite_layer(canvas, region, opacity=alpha_layer, blend_mode=_blend_mode_name(layer), position=(x0, y0))

    # -------------------------------------------------------------- افکت
    def _apply_effects(self, region: Image.Image, effects: dict, scale: float, opacity: float) -> Image.Image:
        if not effects:
            return region
        alpha = region.getchannel("A")

        # سایه‌ی بیرونی
        shadow = effects.get("shadow")
        if shadow and shadow["distance"] >= 0:
            size = max(0.0, shadow["size"] * scale)
            distance = max(0.0, shadow["distance"] * scale)
            angle = math.radians(shadow["angle"])
            dx = int(round(math.cos(angle) * distance))
            dy = int(round(-math.sin(angle) * distance))
            shadow_alpha = alpha.filter(ImageFilter.GaussianBlur(max(0.5, size / 2))) if size else alpha
            shadow_layer = Image.new("RGBA", region.size, shadow["color"] + (0,))
            shadow_layer.putalpha(
                shadow_alpha.point(lambda v: int(v * 0.75 * shadow["opacity"]))
            )
            canvas = Image.new("RGBA", region.size, (0, 0, 0, 0))
            canvas.alpha_composite(shadow_layer, (dx, dy))
            canvas.alpha_composite(region)
            region = canvas

        # درخشش بیرونی
        glow = effects.get("glow")
        if glow:
            size = max(0.5, glow["size"] * scale)
            glow_alpha = alpha.filter(ImageFilter.GaussianBlur(size / 2))
            glow_layer = Image.new("RGBA", region.size, glow["color"] + (0,))
            glow_layer.putalpha(glow_alpha.point(lambda v: int(v * 0.7 * glow["opacity"])))
            canvas = Image.new("RGBA", region.size, (0, 0, 0, 0))
            canvas.alpha_composite(glow_layer)
            canvas.alpha_composite(region)
            region = canvas

        return region


def _hex_to_rgba(value: str) -> tuple[int, int, int, int]:
    value = value.strip().lstrip("#")
    if len(value) == 3:
        value = "".join(c * 2 for c in value)
    if len(value) != 6:
        return (255, 255, 255, 255)
    try:
        return (int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16), 255)
    except ValueError:
        return (255, 255, 255, 255)


def _family_and_style(name: str) -> tuple[str, bool, bool]:
    """نام فونت فتوشاپ را به (خانواده، بولد، ایتالیک) می‌شکند."""
    from .fonts import _split_style

    return _split_style(name)


def _wrap_lines(lines: list[str], measure: Any, max_width: float, rtl: bool) -> list[str]:
    """شکستن خطوط بلند بر اساس عرض قاب (برای متن‌های پاراگرافی فتوشاپ)."""
    out: list[str] = []
    for line in lines:
        if measure(line) <= max_width or not line.strip():
            out.append(line)
            continue
        words = line.split(" ")
        current = ""
        for word in words:
            candidate = f"{current} {word}" if current else word
            if current and measure(candidate) > max_width:
                out.append(current)
                current = word
            else:
                current = candidate
        if current:
            out.append(current)
    return out
