"""
موتور فونت: پیدا کردن فونت‌های نصب‌شده روی سیستم و انتخاب فونت مناسب
(با اولویت فونت فارسی/عربی وقتی متن راست‌به‌چپ است).
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

from PIL import ImageFont

FONT_EXTS = {".ttf", ".otf", ".ttc", ".otc"}
CACHE_VERSION = 3

# فونت‌هایی که برای متن فارسی ترجیح داده می‌شوند (به ترتیب اولویت)
PERSIAN_PREFERRED = [
    "vazirmatn", "vazir", "iransansx", "iransans", "iranyekan", "iranian sans",
    "sahel", "shabnam", "samim", "gandom", "parastoo", "tanha", "estedad",
    "yekanbakh", "yekan", "kalameh", "dana", "peyda", "morabba", "lalezar",
    "nazanin", "badr", "mitra", "titr", "lotus", "zar", "homa",
    "tahoma", "segoeui", "arial", "notonaskharabic", "notosansarabic",
    "amiri", "scheherazadenew", "dejavusans", "dejavuserif", "freeserif",
    "timesnewroman", "couriernew",
]

# فونت‌های عمومی برای متن‌های لاتین (به ترتیب اولویت)
GENERAL_PREFERRED = [
    "arial", "helvetica", "tahoma", "segoeui", "verdana", "calibri",
    "liberationsans", "dejavusans", "notosans", "freesans", "roboto",
    "openSans".lower(), "lato", "timesnewroman", "liberationserif",
    "georgia", "dejavuserif", "couriernew", "liberationmono", "dejavusansmono",
]

# پسوندهایی که نام فونت فتوشاپ به آن‌ها چسبیده است
_FONT_SUFFIXES = (
    "psmt", "mt", "ps", "std", "pro", "lt", "ce", "arabic", "regular",
    "bolditalic", "boldoblique", "italic", "oblique", "bold", "light",
    "semibold", "demibold", "medium", "black", "heavy", "thin", "extralight",
    "ultralight", "condensed", "narrow", "wide", "book", "roman", "display",
    "text", "semicondensed",
)

_ARABIC_TEST = "سیل"
_CACHE_FILE = Path.home() / ".psd_batch_generator_fonts.json"


def _norm(name: str) -> str:
    """نرمال‌سازی نام فونت برای مقایسه."""
    value = (name or "").lower()
    value = re.sub(r"[\s\-_,\(\)\[\]]+", "", value)
    value = value.replace("‌", "")
    return value


def _split_style(name: str) -> tuple[str, bool, bool]:
    """نام فونت فتوشاپ را به (خانواده، بولد، ایتالیک) تبدیل می‌کند."""
    raw = (name or "").strip()
    lower = _norm(raw)
    bold = bool(re.search(r"(bold|black|heavy|extrabold|semibold|demibold)", lower))
    italic = bool(re.search(r"(italic|oblique|kashida)", lower))

    base = raw
    base = re.sub(r"[-_ ]?(Bold|Black|Heavy|ExtraBold|SemiBold|DemiBold|Italic|Oblique|Regular|Light|Medium|Thin|Condensed|Narrow|Wide)\b.*$", "", base, flags=re.I)
    base = re.sub(r"[-_](MT|PSMT|PS|STD|Pro|CE|LT|Arabic)$", "", base, flags=re.I)
    base = re.sub(r"(MT|PSMT)$", "", base)
    if not base.strip():
        base = raw
    return base.strip(), bold, italic


def _token_variants(name: str) -> list[str]:
    """همه‌ی نوشتارهای ممکن نام یک فونت برای مقایسه."""
    base, _, _ = _split_style(name)
    out = {_norm(name), _norm(base)}
    stripped = _norm(base)
    for suffix in _FONT_SUFFIXES:
        if stripped.endswith(suffix) and len(stripped) > len(suffix) + 2:
            out.add(stripped[: -len(suffix)])
    return [x for x in out if x]


@dataclass
class FontEntry:
    path: str
    family: str
    style: str
    index: int = 0
    supports_arabic: bool | None = None

    @property
    def norm_family(self) -> str:
        return _norm(self.family)

    def is_bold(self) -> bool:
        style = (self.style or "").lower()
        return "bold" in style or "black" in style or "heavy" in style or "semibold" in style or "demi" in style

    def is_italic(self) -> bool:
        style = (self.style or "").lower()
        return "italic" in style or "oblique" in style


from .paths import font_dir, resource_dir  # noqa: E402

APP_FONT_DIR = font_dir()


def font_dirs() -> list[Path]:
    dirs: list[Path] = [APP_FONT_DIR]
    env = os.environ.get("PSD_BATCH_FONT_DIRS", "")
    for part in env.split(os.pathsep):
        if part.strip():
            dirs.append(Path(part.strip()))

    if sys.platform.startswith("win"):
        windir = os.environ.get("WINDIR", r"C:\Windows")
        dirs += [Path(windir) / "Fonts"]
        local = os.environ.get("LOCALAPPDATA")
        if local:
            dirs += [Path(local) / "Microsoft" / "Windows" / "Fonts"]
    elif sys.platform == "darwin":
        dirs += [
            Path("/System/Library/Fonts"),
            Path("/Library/Fonts"),
            Path.home() / "Library" / "Fonts",
        ]
    else:
        dirs += [
            Path("/usr/share/fonts"),
            Path("/usr/local/share/fonts"),
            Path.home() / ".fonts",
            Path.home() / ".local" / "share" / "fonts",
        ]
    return [d for d in dirs if d.exists()]


class FontLibrary:
    """فهرست و انتخاب فونت."""

    def __init__(self, extra_dirs: list[str] | None = None):
        self.extra_dirs = [Path(p) for p in (extra_dirs or []) if p]
        self._fonts: list[FontEntry] = []
        self._loaded = False
        self._sizes: dict[tuple[str, int, int], ImageFont.FreeTypeFont] = {}
        self._arabic_cache: dict[str, bool] = {}

    # -------------------------------------------------------------- فهرست
    def load(self, force: bool = False) -> None:
        if self._loaded and not force:
            return
        cached = None if force else self._read_cache()
        if cached is not None:
            self._fonts = [FontEntry(**c) for c in cached]
            self._loaded = True
            return
        self._scan()
        self._write_cache()
        self._loaded = True

    def _read_cache(self) -> list[dict] | None:
        try:
            data = json.loads(_CACHE_FILE.read_text("utf-8"))
            if data.get("version") != CACHE_VERSION:
                return None
            if time.time() - data.get("created", 0) > 60 * 60 * 24 * 30:
                return None
            dirs = [str(d) for d in self._dirs()]
            if data.get("dirs") != dirs:
                return None
            return data.get("fonts")
        except Exception:
            return None

    def _write_cache(self) -> None:
        try:
            _CACHE_FILE.write_text(
                json.dumps(
                    {
                        "version": CACHE_VERSION,
                        "created": time.time(),
                        "dirs": [str(d) for d in self._dirs()],
                        "fonts": [f.__dict__ for f in self._fonts],
                    },
                    ensure_ascii=False,
                ),
                "utf-8",
            )
        except Exception:
            pass

    def _dirs(self) -> list[Path]:
        dirs = font_dirs() + self.extra_dirs
        seen, out = set(), []
        for d in dirs:
            key = str(d)
            if key not in seen and d.exists():
                seen.add(key)
                out.append(d)
        return out

    def _scan(self) -> None:
        self._fonts = []
        for directory in self._dirs():
            for root, _dirs, files in os.walk(directory):
                for filename in files:
                    path = Path(root) / filename
                    if path.suffix.lower() not in FONT_EXTS:
                        continue
                    for entry in self._read_font_file(path):
                        self._fonts.append(entry)

    @staticmethod
    def _read_font_file(path: Path) -> list[FontEntry]:
        out: list[FontEntry] = []
        max_index = 8 if path.suffix.lower() in {".ttc", ".otc"} else 1
        for index in range(max_index):
            try:
                font = ImageFont.truetype(str(path), 16, index=index)
            except Exception:
                break
            try:
                family, style = font.getname()
            except Exception:
                family, style = path.stem, ""
            out.append(FontEntry(path=str(path), family=family or path.stem, style=style or "", index=index))
            if index == 0 and max_index == 1:
                break
        return out

    # ------------------------------------------------------------- انتخاب
    def fonts(self) -> list[FontEntry]:
        self.load()
        return self._fonts

    def supports_arabic(self, path: str, index: int = 0) -> bool:
        """
        آیا فونت نویسه‌های فارسی/عربی را واقعاً دارد؟
        فونت‌هایی که این حروف را ندارند، همه را با «قاب خالی» یکسان می‌کشند؛
        پس اگر شکل نویسه‌های مختلف عربی یکسان بود، یعنی فونت پشتیبانی ندارد.
        """
        key = f"{path}#{index}"
        if key in self._arabic_cache:
            return self._arabic_cache[key]
        ok = False
        try:
            font = ImageFont.truetype(path, 28, index=index)
            masks = []
            for ch in _ARABIC_TEST:
                mask = font.getmask(ch)
                if mask.getbbox() is None:
                    masks = []
                    break
                masks.append(bytes(mask))
            ok = len(masks) >= 2 and len(set(masks)) >= 2
        except Exception:
            ok = False
        self._arabic_cache[key] = ok
        return ok

    def resolve(
        self,
        family_name: str,
        rtl: bool = False,
        override: str | None = None,
        bold: bool = False,
        italic: bool = False,
        sample_text: str = "",
    ) -> FontEntry | None:
        """
        فونت مناسب برای نام فونت فتوشاپ پیدا می‌کند.
          * override: مسیر فایل فونت یا نام خانواده (اولویت اول)
          * اگر فونت قالب روی سیستم نبود و متن فارسی بود، یک فونت فارسی مناسب انتخاب می‌شود
        """
        self.load()

        if override:
            path = Path(override)
            if path.exists() and path.suffix.lower() in FONT_EXTS:
                return FontEntry(path=str(path), family=path.stem, style="", index=0)
            entry = self._match_name(override)
            if entry is not None:
                return self._pick(self._group(entry.norm_family), bold, italic) or entry

        entry = self._match_name(family_name)
        if entry is not None:
            chosen = self._pick(self._group(entry.norm_family), bold, italic) or entry
            if not rtl or self._usable_for_rtl(chosen):
                return chosen

        preferences = PERSIAN_PREFERRED if rtl else GENERAL_PREFERRED
        for wanted in preferences:
            group = self._group_prefix(wanted)
            if not group:
                continue
            if rtl and not any(self._usable_for_rtl(e) for e in group):
                continue
            chosen = self._pick(group, bold, italic)
            if chosen is not None:
                return chosen

        # آخرین راه‌حل: فونتی که نویسه‌های متن را داشته باشد
        for candidate in self._fonts:
            if rtl and not self._usable_for_rtl(candidate):
                continue
            if sample_text and not self._covers(candidate, sample_text):
                continue
            return candidate

        if entry is not None:
            return entry
        return None

    def _group(self, norm_family: str) -> list[FontEntry]:
        return [e for e in self._fonts if e.norm_family == norm_family]

    def _group_prefix(self, token: str) -> list[FontEntry]:
        return [e for e in self._fonts if e.norm_family.startswith(token) or token in e.norm_family]

    @staticmethod
    def _pick(group: list[FontEntry], bold: bool, italic: bool) -> FontEntry | None:
        """بهترین نسخه‌ی یک خانواده‌ی فونت را انتخاب می‌کند."""
        if not group:
            return None
        exact = [e for e in group if e.is_bold() == bold and e.is_italic() == italic]
        if exact:
            return exact[0]
        regular = [e for e in group if not e.is_bold() and not e.is_italic()]
        if regular:
            return regular[0]
        if not bold:
            light = [e for e in group if not e.is_bold()]
            if light:
                return light[0]
        return group[0]

    def _covers(self, entry: FontEntry, text: str) -> bool:
        try:
            return self.text_supported(entry, text)
        except Exception:
            return False

    def _usable_for_rtl(self, entry: FontEntry) -> bool:
        return self.supports_arabic(entry.path, entry.index)

    def _match_name(self, family_name: str) -> FontEntry | None:
        variants = _token_variants(family_name or "")
        if not variants:
            return None
        exact, partial = None, None
        for entry in self._fonts:
            norm = entry.norm_family
            if any(v == norm for v in variants):
                exact = exact or entry
            elif any(v in norm for v in variants) or any(norm in v for v in variants):
                partial = partial or entry
        return exact or partial

    # --------------------------------------------------------------- بارگذاری
    def load_font(
        self,
        entry: FontEntry | None,
        size: float,
        bold: bool = False,
        italic: bool = False,
    ) -> ImageFont.FreeTypeFont:
        size_px = max(1, int(round(size)))
        if entry is None:
            return ImageFont.load_default()
        key = (f"{entry.path}#{entry.index}", size_px, int(bold) * 2 + int(italic))
        if key in self._sizes:
            return self._sizes[key]
        try:
            font = ImageFont.truetype(entry.path, size_px, index=entry.index)
            if hasattr(font, "set_variation_by_axes"):
                try:
                    axes = font.get_variation_axes()
                    if axes:
                        values = []
                        for axis in axes:
                            name = axis.get("name", b"")
                            name = name.decode() if isinstance(name, bytes) else str(name)
                            lo, hi, default = axis["minimum"], axis["maximum"], axis["default"]
                            if "Italic" in name:
                                values.append(hi if italic else lo)
                            elif "Bold" in name or name == "Weight" or "wght" in name.lower():
                                values.append(hi if bold else default)
                            else:
                                values.append(default)
                        font.set_variation_by_axes(values)
                except Exception:
                    pass
        except Exception:
            font = ImageFont.load_default()
        self._sizes[key] = font
        return font

    def text_supported(self, entry: FontEntry | None, text: str) -> bool:
        """آیا فونت همه‌ی نویسه‌های متن را دارد؟"""
        if entry is None:
            return False
        try:
            font = ImageFont.truetype(entry.path, 24, index=entry.index)
        except Exception:
            return False
        for ch in set(text or ""):
            if ch.isspace() or ch == "\u200c":
                continue
            try:
                if font.getmask(ch).getbbox() is None:
                    return False
            except Exception:
                return False
        return True


LIBRARY: FontLibrary | None = None


def library() -> FontLibrary:
    global LIBRARY
    if LIBRARY is None:
        LIBRARY = FontLibrary()
    return LIBRARY
