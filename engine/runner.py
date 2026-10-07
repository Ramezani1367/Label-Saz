"""اجرای دسته‌ای: ترکیب اکسل + قالب فتوشاپ و تولید خروجی برای هر ردیف."""

from __future__ import annotations

import copy
import csv
import os
import re
import threading
import time
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from PIL import Image
from psd_tools import PSDImage

from . import textdata
from .excelio import SheetInfo, cell_text, normalize_title, read_sheets, resolve_column
from .render import PsdRenderer, RenderOptions, RenderReport

INVALID_CHARS = r'[\\/:*?"<>|\r\n\t]'
MAX_NAME_LEN = 120
IMAGE_FORMATS = {"png": ".png", "jpg": ".jpg", "jpeg": ".jpg", "webp": ".webp"}
FORMATS = {**IMAGE_FORMATS, "pdf": ".pdf"}


# --------------------------------------------------------------- تنظیمات


@dataclass
class LayerMapping:
    layer_id: str
    mode: str = "token"                 # token | whole | skip
    column: str | int | None = None     # ستون (برای حالت whole)
    tokens: dict[str, Any] = field(default_factory=dict)  # توکن -> ستون
    direction: str = "auto"             # auto | rtl | ltr (جهت متن لایه)


@dataclass
class SheetSettings:
    name: str
    enabled: bool = True
    name_column_1: str | int | None = None
    name_column_2: str | int | None = None
    separator: str = "-"
    prefix: str = ""
    suffix: str = ""
    row_from: int = 1        # شماره‌ی ردیف داده (۱ = اولین ردیف داده)
    row_to: int | None = None
    folder: bool = True      # ساخت زیرپوشه به نام شیت
    psd_path: str | None = None          # قالب اختصاصی این شیت
    template_column: str | int | None = None  # ستون انتخاب قالب هر ردیف
    template_dir: str | None = None      # پوشه‌ی قالب‌های جایگزین


@dataclass
class JobSettings:
    excel_path: str = ""
    psd_path: str = ""
    out_dir: str = ""
    sheets: list[SheetSettings] = field(default_factory=list)
    layers: list[LayerMapping] = field(default_factory=list)
    header_row: int = 1
    image_format: str = "png"
    jpeg_quality: int = 95
    save_psd: bool = False
    overwrite: bool = True
    pdf_mode: str = "sheet"                  # each = یک PDF برای هر ردیف | sheet = یکیپارچه در هر پوشه | all = یکپارچه‌ی همه‌ی شیت‌ها
    pdf_also_individual: bool = False        # در حالت یکپارچه، PDF هر ردیف هم جداگانه ذخیره شود
    pdf_all_name: str = "همه-صفحات"          # نام فایل PDF یکپارچه‌ی کل (حالت all)
    pdf_dpi: int = 150
    csv_index: bool = False                  # ساخت فایل CSV فهرست خروجی‌ها
    render: RenderOptions = field(default_factory=RenderOptions)


@dataclass
class RowOutput:
    sheet: str
    row: int
    file: str
    values: list[str] = field(default_factory=list)


# ------------------------------------------------------------- کمک‌کننده‌ها


def sanitize_filename(value: str, fallback: str = "بدون‌نام") -> str:
    text = (value or "").strip()
    text = re.sub(INVALID_CHARS, "-", text)
    text = re.sub(r"\s+", " ", text)
    text = text.strip(" .-")
    if len(text) > MAX_NAME_LEN:
        text = text[:MAX_NAME_LEN].rstrip()
    return text or fallback


def unique_path(folder: Path, stem: str, extension: str, used: set[str], avoid_existing: bool = True) -> Path:
    candidate = f"{stem}{extension}"
    counter = 2
    while candidate.lower() in used or (avoid_existing and (folder / candidate).exists()):
        candidate = f"{stem}_{counter}{extension}"
        counter += 1
        if counter > 9999:
            break
    used.add(candidate.lower())
    return folder / candidate


def build_layer_index(psd: Any) -> list[dict]:
    """فهرست لایه‌های متنی سند برای نمایش در رابط کاربری."""
    out = []
    for i, layer in enumerate(textdata.iter_text_layers(psd, include_hidden=True)):
        try:
            plain = textdata.to_plain(layer.text).rstrip("\n")
        except Exception:
            plain = ""
        out.append(
            {
                "id": f"L{i}",
                "index": i,
                "name": textdata.layer_display_name(layer),
                "path": textdata.layer_path(layer),
                "text": plain,
                "preview": textdata.layer_preview_text(layer),
                "tokens": textdata.extract_tokens(plain),
                "fonts": textdata.layer_font_names(layer),
                "visible": bool(getattr(layer, "visible", True)),
                "rtl": textdata.has_rtl(plain),
                "effects": bool(getattr(layer, "effects", None)),
            }
        )
    return out


def auto_match_columns(tokens: list[str], sheet: SheetInfo) -> dict[str, int]:
    """تطبیق خودکار توکن‌ها با ستون‌های اکسل."""
    mapping: dict[str, int] = {}
    by_norm = {normalize_title(c.title): c.index for c in sheet.columns}
    by_unique = {normalize_title(c.unique_title): c.index for c in sheet.columns}
    for token in tokens:
        norm = normalize_title(token)
        if norm in by_norm:
            mapping[token] = by_norm[norm]
            continue
        if norm in by_unique:
            mapping[token] = by_unique[norm]
            continue
        for column in sheet.columns:
            col_norm = normalize_title(column.title)
            if col_norm and (col_norm in norm or norm in col_norm) and abs(len(col_norm) - len(norm)) <= 12:
                mapping[token] = column.index
                break
    return mapping


# ------------------------------------------------------------------ اجرا


class BatchRunner:
    def __init__(self, settings: JobSettings):
        self.settings = settings
        self.stop_flag = threading.Event()
        self.total = 0
        self.done = 0
        self.errors: list[dict] = []
        self.log: list[str] = []
        self.produced: list[str] = []
        self.rows: list[RowOutput] = []

    # -------------------------------------------------------------- کمکی
    def _log(self, message: str) -> None:
        stamp = time.strftime("%H:%M:%S")
        self.log.append(f"[{stamp}] {message}")
        if len(self.log) > 400:
            del self.log[:200]

    def _values_for_row(self, sheet: SheetInfo, row_index: int, mapping: LayerMapping) -> dict[str, str]:
        values: dict[str, str] = {}
        for token, column_key in (mapping.tokens or {}).items():
            column = resolve_column(sheet, column_key)
            if column is None:
                continue
            values[token] = sheet.cell(row_index, column.index)
        return values

    def _layer_text_after(self, layer: Any, sheet: SheetInfo, row_index: int, mapping: LayerMapping) -> tuple[str, bool]:
        original = textdata.to_plain(layer.text).rstrip("\n")
        if mapping.mode == "skip":
            return original, False
        if mapping.mode == "whole":
            column = resolve_column(sheet, mapping.column)
            if column is None:
                return original, False
            new_text = sheet.cell(row_index, column.index)
            return new_text, new_text != original
        if mapping.mode == "token":
            values = self._values_for_row(sheet, row_index, mapping)
            new_text, used = textdata.fill_tokens(original, values)
            return new_text, bool(used) and new_text != original
        return original, False

    def _template_for_row(self, sheet: SheetInfo, sheet_settings: SheetSettings, row_index: int) -> Path:
        """قالب مناسب این ردیف (قالب شیت یا قالب انتخابی از ستون)."""
        default = Path(sheet_settings.psd_path or self.settings.psd_path)
        column = resolve_column(sheet, sheet_settings.template_column)
        if column is None:
            return default
        value = sheet.cell(row_index, column.index)
        if not value:
            return default
        folders = []
        if sheet_settings.template_dir:
            folders.append(Path(sheet_settings.template_dir))
        folders.append(default.parent)
        found = find_image(value, folders, extra_exts=False)  # جست‌وجوی مسیر فایل
        if found is None:
            for folder in folders:
                for ext in (".psd", ".psb"):
                    candidate = Path(folder) / f"{value}{ext}"
                    if candidate.is_file():
                        found = candidate
                        break
                if found:
                    break
        if found is None:
            self._log(f"قالب «{value}» پیدا نشد؛ قالب پیش‌فرض استفاده شد.")
            return default
        return found

    def _file_stem(self, sheet: SheetInfo, sheet_settings: SheetSettings, row_index: int) -> str:
        col1 = resolve_column(sheet, sheet_settings.name_column_1)
        col2 = resolve_column(sheet, sheet_settings.name_column_2)
        parts = []
        if col1:
            parts.append(sheet.cell(row_index, col1.index))
        if col2:
            value = sheet.cell(row_index, col2.index)
            if value:
                parts.append(value)
        separator = sheet_settings.separator if sheet_settings.separator is not None else "-"
        stem = separator.join([p for p in parts if p]) if len(parts) > 1 else (parts[0] if parts else "")
        stem = f"{sheet_settings.prefix}{stem}{sheet_settings.suffix}"
        if not stem.strip():
            stem = f"ردیف-{row_index + 1}"
        return sanitize_filename(stem)

    # -------------------------------------------------------------- ردیف
    def _render_row(self, sheet: SheetInfo, row_index: int, psd_path: Path) -> tuple[Image.Image, Any, list[str], RenderReport, list[dict]]:
        psd = PSDImage.open(str(psd_path))
        text_index = {item["id"]: item for item in build_layer_index(psd)}
        report = RenderReport()
        changed: list[str] = []
        details: list[dict] = []

        for mapping in self.settings.layers:
            if mapping.mode == "skip":
                continue
            info = text_index.get(mapping.layer_id)
            if info is None:
                continue
            layer = self._find_text_layer(psd, info)
            if layer is None:
                continue
            original = textdata.to_plain(layer.text).rstrip("\n")
            new_text, is_changed = self._layer_text_after(layer, sheet, row_index, mapping)
            if is_changed:
                textdata.set_layer_text(layer, new_text)
                changed.append(textdata.layer_display_name(layer))
                details.append(
                    {"layer": textdata.layer_display_name(layer), "kind": "text",
                     "before": original, "after": new_text}
                )

        renderer = PsdRenderer(self.settings.render)
        image = renderer.render(psd, report, self._layer_options())
        return image, psd, changed, report, details

    def _layer_options(self) -> dict[int, dict]:
        """تنظیمات مخصوص هر لایه‌ی متنی (مثل جهت متن)."""
        out: dict[int, dict] = {}
        for mapping in self.settings.layers:
            if mapping.mode == "skip" or not mapping.layer_id.startswith("L"):
                continue
            try:
                index = int(mapping.layer_id[1:])
            except ValueError:
                continue
            if mapping.direction and mapping.direction != "auto":
                out.setdefault(index, {})["direction"] = mapping.direction
        return out

    @staticmethod
    def _find_text_layer(psd: Any, info: dict) -> Any | None:
        index = int(info.get("index", -1))
        for i, layer in enumerate(textdata.iter_text_layers(psd, include_hidden=True)):
            if i == index:
                return layer
        return None

    # --------------------------------------------------------------- اجرا
    def run(self, progress_cb: Callable[[dict], None] | None = None) -> dict:
        settings = self.settings
        started = time.time()
        sheets = read_sheets(settings.excel_path, header_row=settings.header_row)
        by_name = {s.name: s for s in sheets}

        selected: list[tuple[SheetInfo, SheetSettings]] = []
        for sheet_settings in settings.sheets:
            if not sheet_settings.enabled:
                continue
            sheet = by_name.get(sheet_settings.name)
            if sheet is None:
                continue
            selected.append((sheet, sheet_settings))

        self.total = sum(
            max(0, min(ss.row_to or sheet.row_count, sheet.row_count) - (ss.row_from - 1))
            for sheet, ss in selected
        )

        out_root = Path(settings.out_dir)
        out_root.mkdir(parents=True, exist_ok=True)
        image_extension = IMAGE_FORMATS.get(settings.image_format.lower())
        is_pdf = settings.image_format.lower() == "pdf"
        pdf_mode = (settings.pdf_mode or "sheet").lower()
        if pdf_mode not in ("each", "sheet", "all"):
            pdf_mode = "sheet"
        merge_per_sheet = is_pdf and pdf_mode in ("sheet", "all")   # یکپارچه در هر پوشه‌ی شیت
        merge_all = is_pdf and pdf_mode == "all"                    # یکپارچه‌ی همه‌ی شیت‌ها در یک فایل
        merge_all_pages: list[Image.Image] = []
        merge_all_name = sanitize_filename(settings.pdf_all_name or "همه-صفحات") + ".pdf"

        for sheet, sheet_settings in selected:
            folder = out_root / sheet.name if sheet_settings.folder else out_root
            folder.mkdir(parents=True, exist_ok=True)
            used_names: set[str] = set()
            start = max(0, (sheet_settings.row_from or 1) - 1)
            end = min(sheet.row_count, sheet_settings.row_to or sheet.row_count)

            pdf_pages: list[Image.Image] = []
            pdf_name = sanitize_filename(sheet.name) + ".pdf"
            index_rows: list[list[str]] = []

            for row_index in range(start, end):
                if self.stop_flag.is_set():
                    self._log("عملیات توسط کاربر متوقف شد.")
                    if merge_per_sheet and pdf_pages:
                        self._flush_pdf(folder, pdf_name, pdf_pages)
                    if merge_all and merge_all_pages:
                        self._flush_pdf(out_root, merge_all_name, merge_all_pages)
                    return self._result(started, stopped=True)
                try:
                    psd_path = self._template_for_row(sheet, sheet_settings, row_index)
                    stem = self._file_stem(sheet, sheet_settings, row_index)
                    image, psd, changed, report, details = self._render_row(sheet, row_index, psd_path)

                    saved_name = ""
                    if is_pdf and merge_per_sheet:
                        # PDF یکپارچه (هر شیت یک فایل، و در حالت all همه در یک فایل)
                        page = image.convert("RGB")
                        pdf_pages.append(page)
                        if merge_all:
                            merge_all_pages.append(page)
                        single_target = None
                        if settings.pdf_also_individual:
                            single_target = unique_path(folder, stem, ".pdf", used_names, avoid_existing=not settings.overwrite)
                            page.save(single_target, resolution=float(settings.pdf_dpi), quality=int(settings.jpeg_quality))
                        if settings.save_psd:
                            try:
                                psd.save(str(folder / f"{stem}.psd"), encoding="utf-8")
                            except Exception as exc:
                                self._log(f"ذخیره‌ی PSD ناموفق بود: {exc}")
                        saved_name = single_target.name if single_target else pdf_name
                        self._after_save(single_target, sheet, row_index, changed, index_rows, file_name=saved_name)
                        if progress_cb:
                            progress_cb(self._progress(folder / pdf_name, sheet.name, row_index, changed))
                    else:
                        if is_pdf:
                            extension = ".pdf"
                        else:
                            extension = image_extension or ".png"
                        target = unique_path(folder, stem, extension, used_names, avoid_existing=not settings.overwrite)
                        if extension == ".pdf":
                            image.convert("RGB").save(target, resolution=float(settings.pdf_dpi), quality=int(settings.jpeg_quality))
                        elif extension in (".jpg", ".jpeg"):
                            image.convert("RGB").save(target, quality=int(settings.jpeg_quality), subsampling=0)
                        else:
                            image.save(target)
                        if settings.save_psd:
                            try:
                                psd.save(str(target.with_suffix(".psd")), encoding="utf-8")
                            except Exception as exc:
                                self._log(f"ذخیره‌ی PSD ناموفق بود: {exc}")
                        saved_name = target.name
                        self._after_save(target, sheet, row_index, changed, index_rows)
                        if progress_cb:
                            progress_cb(self._progress(target, sheet.name, row_index, changed))
                    for warning in report.warnings:
                        self._log(f"  ⚠ {warning}")
                    if changed:
                        self._log(f"{saved_name} ← {', '.join(changed)}")
                except Exception as exc:
                    error = {
                        "sheet": sheet.name,
                        "row": row_index + 1,
                        "error": str(exc),
                        "trace": traceback.format_exc(limit=3),
                    }
                    self.errors.append(error)
                    self._log(f"خطا در شیت «{sheet.name}» ردیف {row_index + 1}: {exc}")
                    self.done += 1
                    if progress_cb:
                        progress_cb(self._progress(None, sheet.name, row_index, []))

            if merge_per_sheet and pdf_pages:
                self._flush_pdf(folder, pdf_name, pdf_pages)
                self.produced.append(str(folder / pdf_name))
                self._log(f"PDF یکپارچه‌ی این پوشه ساخته شد: {pdf_name} ({len(pdf_pages)} صفحه)")

            if settings.csv_index and index_rows:
                csv_path = folder / "_فهرست-خروجی.csv"
                try:
                    with csv_path.open("w", newline="", encoding="utf-8-sig") as handle:
                        writer = csv.writer(handle)
                        writer.writerow(["شیت", "ردیف", "نام فایل"] + [c.unique_title for c in sheet.columns])
                        writer.writerows(index_rows)
                    self._log(f"فهرست CSV ساخته شد: {csv_path.name}")
                except Exception as exc:
                    self._log(f"ساخت CSV ناموفق بود: {exc}")

        if merge_all and merge_all_pages:
            self._flush_pdf(out_root, merge_all_name, merge_all_pages)
            self.produced.append(str(out_root / merge_all_name))
            self._log(f"PDF یکپارچه‌ی همه‌ی شیت‌ها ساخته شد: {merge_all_name} ({len(merge_all_pages)} صفحه)")

        self._log(f"پایان عملیات؛ {len(self.produced)} فایل در {out_root}")
        return self._result(started)

    def _flush_pdf(self, folder: Path, name: str, pages: list[Image.Image]) -> None:
        if not pages:
            return
        try:
            target = folder / name
            first, rest = pages[0], pages[1:]
            first.save(
                target,
                save_all=True,
                append_images=rest,
                resolution=float(self.settings.pdf_dpi),
                quality=int(self.settings.jpeg_quality),
            )
        except Exception as exc:
            self._log(f"ساخت PDF ناموفق بود: {exc}")

    def _after_save(
        self,
        target: Path | None,
        sheet: SheetInfo,
        row_index: int,
        changed: list[str],
        index_rows: list[list[str]],
        file_name: str | None = None,
    ) -> None:
        """ثبت خروجی یک ردیف (target=None یعنی این ردیف فقط داخل PDF یکپارچه آمده است)."""
        if target is not None:
            self.produced.append(str(target))
        self.done += 1
        name = file_name or (target.name if target is not None else "")
        values = [sheet.cell(row_index, c.index) for c in sheet.columns]
        self.rows.append(
            RowOutput(
                sheet=sheet.name,
                row=row_index + 1,
                file=str(target) if target is not None else name,
                values=values,
            )
        )
        if self.settings.csv_index:
            index_rows.append([sheet.name, str(row_index + 1), name] + values)

    # ------------------------------------------------------------ پیش‌نمایش
    def render_single(self, sheet_name: str, row_index: int) -> tuple[Any, RenderReport, list[str], list[dict]]:
        """رندر یک ردیف مشخص (برای پیش‌نمایش)."""
        settings = self.settings
        sheets = read_sheets(settings.excel_path, header_row=settings.header_row)
        sheet = next((s for s in sheets if s.name == sheet_name), None)
        if sheet is None:
            raise ValueError(f"شیت «{sheet_name}» پیدا نشد.")
        row_index = max(0, min(row_index, sheet.row_count - 1))
        sheet_settings = next((s for s in settings.sheets if s.name == sheet_name), None)
        psd_path = self._template_for_row(sheet, sheet_settings, row_index) if sheet_settings else Path(settings.psd_path)
        image, _psd, changed, report, details = self._render_row(sheet, row_index, Path(psd_path))
        return image, report, changed, details

    # ------------------------------------------------------------ وضعیت
    def _progress(self, path: Path | None, sheet: str, row_index: int, changed: list[str]) -> dict:
        return {
            "done": self.done,
            "total": self.total,
            "sheet": sheet,
            "row": row_index + 1,
            "file": str(path) if path else None,
            "changed": changed,
            "errors": len(self.errors),
            "last_log": self.log[-6:],
        }

    def _result(self, started: float, stopped: bool = False) -> dict:
        return {
            "ok": not self.errors,
            "done": self.done,
            "total": self.total,
            "errors": self.errors,
            "log": self.log,
            "produced": self.produced,
            "elapsed": round(time.time() - started, 2),
            "stopped": stopped,
            "out_dir": self.settings.out_dir,
        }
