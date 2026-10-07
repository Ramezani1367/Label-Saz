"""
کار با لایه‌های متنی فایل فتوشاپ (PSD).

این ماژول:
  * متن لایه‌های متنی را می‌خواند
  * متن لایه را به‌صورت ایمن جایگزین می‌کند (هم داده‌ی یونیکد و هم EngineData فتوشاپ)
  * طول «ران»های استایل را متناسب تنظیم می‌کند تا استایل متن حفظ شود
  * پلیس‌هولدرهای داخل متن (مثل ‎{{نام}}‎) را پیدا و جایگزین می‌کند
"""

from __future__ import annotations

import re
from typing import Any, Iterator

from psd_tools.constants import Tag

# ---------------------------------------------------------------- نویسه‌ها

_RTL_RE = re.compile(r"[\u0590-\u08FF\uFB1D-\uFDFF\uFE70-\uFEFF]")
_TOKEN_RE = re.compile(r"\{\{\s*([^{}]+?)\s*\}\}|\{\s*([^{}]+?)\s*\}")


def has_rtl(text: str) -> bool:
    """آیا متن شامل نویسه‌های راست‌به‌چپ (فارسی/عربی/عبری) است؟"""
    return bool(_RTL_RE.search(text or ""))


def first_strong_is_rtl(text: str) -> bool:
    """اولین نویسه‌ی جهت‌دار در متن راست‌به‌چپ است؟ (برای تعیین جهت پاراگراف)"""
    for ch in text or "":
        if _RTL_RE.match(ch):
            return True
        if ch.isalpha() and ch.isascii():
            return False
    return has_rtl(text)


def to_plain(text: str) -> str:
    """تبدیل جداکننده‌ی خط فتوشاپ (CR) به خط جدید معمولی."""
    return (text or "").replace("\r\n", "\n").replace("\r", "\n")


def to_psd(text: str) -> str:
    """تبدیل خطوط جدید ورودی کاربر به قالب فتوشاپ (CR)."""
    return (text or "").replace("\r\n", "\n").replace("\r", "\n").replace("\n", "\r")


def utf16_len(text: str) -> int:
    """طول متن بر حسب واحدهای UTF-16 (همان چیزی که موتور متن فتوشاپ می‌شمارد)."""
    return len((text or "").encode("utf-16-le")) // 2


# ------------------------------------------------------------ لایه‌های متنی


def is_text_layer(layer: Any) -> bool:
    return getattr(layer, "kind", None) == "type"


def iter_text_layers(psd: Any, include_hidden: bool = True) -> Iterator[Any]:
    """همه‌ی لایه‌های متنی سند، از بالاترین لایه به پایین‌ترین."""
    for layer in psd.descendants():
        if is_text_layer(layer):
            if include_hidden or _layer_chain_visible(layer):
                yield layer


def _layer_chain_visible(layer: Any) -> bool:
    node = layer
    while node is not None:
        if not getattr(node, "visible", True):
            return False
        node = getattr(node, "_parent", None)
    return True


def layer_display_name(layer: Any) -> str:
    name = getattr(layer, "name", "") or ""
    return name.strip() or "لایه‌ی بی‌نام"


def layer_path(layer: Any) -> str:
    """مسیر لایه داخل گروه‌ها، مثل: گروه ۱ / عنوان"""
    parts = [layer_display_name(layer)]
    node = getattr(layer, "_parent", None)
    while node is not None and hasattr(node, "name"):
        try:
            parts.insert(0, node.name or "")
        except Exception:
            break
        node = getattr(node, "_parent", None)
    return " / ".join([p for p in parts if p])


def layer_preview_text(layer: Any, max_len: int = 90) -> str:
    try:
        text = to_plain(layer.text)
    except Exception:
        text = ""
    text = text.strip("\n")
    if len(text) > max_len:
        text = text[: max_len - 1] + "…"
    return text


def layer_font_names(layer: Any) -> list[str]:
    """فونت‌های استفاده‌شده در لایه."""
    names: list[str] = []
    try:
        fontset = layer.resource_dict["FontSet"]
        engine = layer.engine_dict
        for run in engine["StyleRun"]["RunArray"]:
            idx = run["StyleSheet"]["StyleSheetData"].get("Font")
            if idx is None:
                continue
            try:
                fname = fontset[idx.value]["Name"].value
            except Exception:
                continue
            if fname not in names:
                names.append(str(fname))
    except Exception:
        pass
    return names


# ------------------------------------------------------- تنظیم متن لایه


def _run_length_array(container: Any) -> Any | None:
    if container is None:
        return None
    try:
        if "RunLengthArray" in container:
            return container["RunLengthArray"]
    except Exception:
        return None
    return None


def _resize_runs(container: Any, old_len: int, new_len: int) -> None:
    """
    طول ران‌های استایل را طوری تغییر می‌دهد که مجموعشان برابر طول متن جدید شود.
    (استایل‌های مختلف متن به‌صورت نسبی حفظ می‌شوند.)
    """
    if container is None or old_len <= 0:
        return
    rla = _run_length_array(container)
    if rla is None or len(rla) == 0:
        return

    lengths = [int(getattr(x, "value", x) or 0) for x in rla]
    total = sum(lengths) or old_len
    scaled = [max(1, round(new_len * (l / total))) for l in lengths]

    # اصلاح گردکردن‌ها تا مجموع دقیقاً برابر طول متن جدید شود
    diff = new_len - sum(scaled)
    i = 0
    while diff != 0 and scaled:
        idx = i % len(scaled)
        if diff > 0:
            scaled[idx] += 1
            diff -= 1
        elif scaled[idx] > 1:
            scaled[idx] -= 1
            diff += 1
        i += 1
        if i > 10000:
            break

    while len(rla) > 1:
        rla.pop()

    first = rla[0]
    if hasattr(first, "value"):
        first.value = scaled[0]
        maker = type(first)
    else:  # pragma: no cover - نادر
        from psd_tools.psd.engine_data import Integer

        rla[0] = Integer(scaled[0])
        maker = Integer

    for value in scaled[1:]:
        rla.append(maker(value))


def set_layer_text(layer: Any, new_text: str) -> None:
    """
    متن لایه‌ی متنی را جایگزین می‌کند و طول ران‌های استایل را هم‌ارز می‌کند.
    جداکننده‌ی خط = \n (به \r فتوشاپ تبدیل می‌شود).
    """
    data = layer.tagged_blocks.get_data(Tag.TYPE_TOOL_OBJECT_SETTING)
    if data is None:
        raise ValueError("داده‌ی لایه‌ی متنی پیدا نشد.")
    text_data = data.text_data

    old_text = ""
    try:
        old_text = text_data[b"Txt "].value
    except Exception:
        try:
            old_text = layer.text
        except Exception:
            old_text = ""

    body = to_psd(new_text).rstrip("\r")
    keeps_trailing = old_text.endswith("\r")
    written = body + ("\r" if keeps_trailing else "")

    if b"Txt " in text_data:
        text_data[b"Txt "].value = written

    engine = text_data[b"EngineData"].value["EngineDict"]
    engine["Editor"]["Text"].value = written

    old_len = utf16_len(old_text)
    new_len = utf16_len(written)
    _resize_runs(engine.get("StyleRun"), old_len, new_len)
    _resize_runs(engine.get("ParagraphRun"), old_len, new_len)


# ------------------------------------------------------------- پلیس‌هولدرها


def extract_tokens(text: str) -> list[str]:
    """همه‌ی توکن‌های ‎{{...}}‎ یا ‎{...}‎ داخل متن."""
    found: list[str] = []
    for m in _TOKEN_RE.finditer(text or ""):
        token = (m.group(1) or m.group(2) or "").strip()
        if token and token not in found:
            found.append(token)
    return found


def fill_tokens(text: str, values: dict[str, str]) -> tuple[str, list[str]]:
    """جایگزینی توکن‌ها؛ برمی‌گرداند (متن جدید، توکن‌های جاشده)."""
    used: list[str] = []

    def _sub(m: re.Match) -> str:
        token = (m.group(1) or m.group(2) or "").strip()
        if token in values:
            used.append(token)
            return str(values[token])
        return m.group(0)

    return _TOKEN_RE.sub(_sub, text or ""), used
