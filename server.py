"""
سرور وب برنامه‌ی «تولید انبوه تصویر از قالب فتوشاپ».

اجرا:  python server.py  [--port 8756] [--no-browser]
"""

from __future__ import annotations

import argparse
import base64
import io
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import traceback
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))

from engine import paths, textdata  # noqa: E402
from engine.excelio import read_sheets  # noqa: E402
from engine.fonts import library  # noqa: E402
from engine.render import RenderOptions  # noqa: E402
from engine.runner import (  # noqa: E402
    BatchRunner,
    JobSettings,
    LayerMapping,
    SheetSettings,
    auto_match_columns,
    build_layer_index,
)

from psd_tools import PSDImage  # noqa: E402

WEB_DIR = paths.resource_dir() / "web"
SETTINGS_FILE = paths.user_file("settings.json")
AUTO_MATCH_THRESHOLD = 2


# ------------------------------------------------------------------ کمکی


def _load_job_settings(data: dict) -> JobSettings:
    render_data = data.get("render") or {}
    render = RenderOptions(
        scale=float(render_data.get("scale", 1.0) or 1.0),
        supersample=float(render_data.get("supersample", 2.0) or 2.0),
        font_scale=float(render_data.get("font_scale", 1.0) or 1.0),
        line_height=float(render_data.get("line_height", 1.0) or 1.0),
        offset_x=float(render_data.get("offset_x", 0.0) or 0.0),
        offset_y=float(render_data.get("offset_y", 0.0) or 0.0),
        font_override=(render_data.get("font_override") or None),
        transparent=bool(render_data.get("transparent", False)),
        background=(render_data.get("background") or None),
        ignore_effects=bool(render_data.get("ignore_effects", False)),
    )
    sheets = [
        SheetSettings(
            name=s.get("name", ""),
            enabled=bool(s.get("enabled", True)),
            name_column_1=s.get("name_column_1") or None,
            name_column_2=s.get("name_column_2") or None,
            separator=s.get("separator", "-"),
            prefix=s.get("prefix", ""),
            suffix=s.get("suffix", ""),
            row_from=int(s.get("row_from") or 1),
            row_to=(int(s["row_to"]) if s.get("row_to") else None),
            folder=bool(s.get("folder", True)),
            psd_path=s.get("psd_path") or None,
            template_column=s.get("template_column") or None,
            template_dir=s.get("template_dir") or None,
        )
        for s in (data.get("sheets") or [])
    ]
    layers = [
        LayerMapping(
            layer_id=l.get("layer_id", ""),
            mode=l.get("mode", "token"),
            column=l.get("column") or None,
            tokens={k: v for k, v in (l.get("tokens") or {}).items() if v},
            direction=l.get("direction", "auto"),
        )
        for l in (data.get("layers") or [])
    ]
    return JobSettings(
        excel_path=data.get("excel_path", ""),
        psd_path=data.get("psd_path", ""),
        out_dir=data.get("out_dir", ""),
        sheets=sheets,
        layers=layers,
        header_row=int(data.get("header_row") or 1),
        image_format=data.get("image_format", "png"),
        jpeg_quality=int(data.get("jpeg_quality") or 95),
        save_psd=bool(data.get("save_psd", False)),
        overwrite=bool(data.get("overwrite", True)),
        pdf_mode=(data.get("pdf_mode") or "sheet"),
        pdf_also_individual=bool(data.get("pdf_also_individual", False)),
        pdf_all_name=str(data.get("pdf_all_name") or "همه-صفحات"),
        pdf_dpi=int(data.get("pdf_dpi") or 150),
        csv_index=bool(data.get("csv_index", False)),
        render=render,
    )


def _layer_info_list(psd_path: str) -> list[dict]:
    psd = PSDImage.open(psd_path)
    return build_layer_index(psd)


def analyze(data: dict) -> dict:
    excel_path = data.get("excel_path") or ""
    psd_path = data.get("psd_path") or ""
    header_row = int(data.get("header_row") or 1)

    warnings: list[str] = []
    sheets_payload = []
    all_tokens: list[str] = []
    sheets: list = []

    if excel_path and Path(excel_path).exists():
        sheets = read_sheets(excel_path, header_row=header_row)
        for sheet in sheets:
            sheets_payload.append(
                {
                    "name": sheet.name,
                    "index": sheet.index,
                    "row_count": sheet.row_count,
                    "columns": [
                        {
                            "index": c.index,
                            "letter": c.letter,
                            "title": c.title,
                            "unique_title": c.unique_title,
                        }
                        for c in sheet.columns
                    ],
                    "sample_rows": sheet.sample_rows(4),
                }
            )
    elif excel_path:
        warnings.append("فایل اکسل پیدا نشد؛ مسیر را بررسی کنید.")

    layers_payload = []
    psd_meta = None
    if psd_path and Path(psd_path).exists():
        try:
            psd_meta = _psd_meta(psd_path)
            layers_payload = build_layer_index(PSDImage.open(psd_path))
        except Exception as exc:
            warnings.append(f"خواندن فایل فتوشاپ ناموفق بود: {exc}")
    elif psd_path:
        warnings.append("فایل فتوشاپ پیدا نشد؛ مسیر را بررسی کنید.")

    for layer in layers_payload:
        for token in layer.get("tokens", []):
            if token not in all_tokens:
                all_tokens.append(token)

    # تطبیق خودکار توکن‌ها با ستون‌ها (بر اساس شیت اول)
    token_map: dict[str, str] = {}
    if sheets and all_tokens:
        matches: dict[str, list[str]] = {token: [] for token in all_tokens}
        for sheet in sheets:
            auto = auto_match_columns(all_tokens, sheet)
            for token, column_index in auto.items():
                column = next((c for c in sheet.columns if c.index == column_index), None)
                if column is not None:
                    matches[token].append(column.unique_title or column.title)
        for token, hits in matches.items():
            if hits:
                token_map[token] = hits[0]

    # پیشنهاد ستون‌های نام فایل
    suggested_sheets = []
    for sheet in sheets:
        col1 = sheet.columns[0].letter if len(sheet.columns) > 0 else None
        col2 = sheet.columns[1].letter if len(sheet.columns) > 1 else None
        for column in sheet.columns:
            from engine.excelio import normalize_title

            if any(k in normalize_title(column.title) for k in ("نام", "name", "title", "عنوان")):
                col1 = column.letter
                break
        suggested_sheets.append(
            {"name": sheet.name, "name_column_1": col1, "name_column_2": col2}
        )

    if not all_tokens and layers_payload:
        warnings.append(
            "در هیچ لایه‌ی متنی پلیس‌هولدر ‎{{...}}‎ پیدا نشد. می‌توانید حالت «کل متن لایه = یک ستون» را انتخاب کنید."
        )

    return {
        "ok": True,
        "sheets": sheets_payload,
        "layers": layers_payload,
        "tokens": all_tokens,
        "token_map": token_map,
        "suggested_sheets": suggested_sheets,
        "warnings": warnings,
        "psd": psd_meta,
        "fonts": _font_summary(layers_payload),
    }


def _psd_meta(path: str) -> dict:
    try:
        psd = PSDImage.open(path)
        return {"width": psd.width, "height": psd.height, "color_mode": str(psd.color_mode),
                "path": str(path), "name": Path(path).name}
    except Exception as exc:
        return {"error": str(exc)}


def _font_summary(layers: list[dict]) -> dict:
    lib = library()
    lib.load()
    out: dict[str, dict] = {}
    for layer in layers:
        text = layer.get("text", "")
        rtl = textdata.first_strong_is_rtl(text)
        for family in layer.get("fonts", []):
            key = f"{family}|{rtl}"
            if key in out:
                continue
            try:
                entry = lib.resolve(family, rtl=rtl, bold=False, italic=False)
            except Exception:
                entry = None
            out[key] = {
                "family": family,
                "rtl": rtl,
                "resolved": entry.family if entry else None,
                "path": entry.path if entry else None,
                "ok": bool(entry and lib.text_supported(entry, text[:80])),
            }
    return out


def preview(data: dict) -> dict:
    settings = _load_job_settings(data)
    sheet_name = data.get("sheet") or (settings.sheets[0].name if settings.sheets else "")
    row = int(data.get("row") or 0)
    if not settings.excel_path or not settings.psd_path:
        raise ValueError("ابتدا فایل اکسل و فایل فتوشاپ را انتخاب کنید.")
    runner = BatchRunner(settings)
    image, report, changed, details = runner.render_single(sheet_name, row)
    buffer = io.BytesIO()
    if settings.image_format.lower() in ("jpg", "jpeg") and not settings.render.transparent:
        image.convert("RGB").save(buffer, format="JPEG", quality=int(settings.jpeg_quality))
        mime = "image/jpeg"
    else:
        image.save(buffer, format="PNG")
        mime = "image/png"
    payload = base64.b64encode(buffer.getvalue()).decode("ascii")
    return {
        "ok": True,
        "image": f"data:{mime};base64,{payload}",
        "changed": changed,
        "details": details,
        "report": {
            "layers": [
                {"layer": r.layer, "text": r.text, "font_used": r.font_used,
                 "font_missing": r.font_missing, "warnings": r.warnings}
                for r in report.layers
            ],
            "warnings": report.warnings,
        },
        "size": list(image.size),
    }


# ------------------------------------------------------------ مدیریت کار


class JobState:
    def __init__(self):
        self.lock = threading.Lock()
        self.thread: threading.Thread | None = None
        self.runner: BatchRunner | None = None
        self.status: dict = {"state": "idle", "done": 0, "total": 0}
        self.started = 0.0

    def start(self, data: dict) -> dict:
        with self.lock:
            if self.thread and self.thread.is_alive():
                raise RuntimeError("یک عملیات در حال اجراست؛ ابتدا آن را متوقف کنید.")
            settings = _load_job_settings(data)
            if not settings.excel_path or not settings.psd_path or not settings.out_dir:
                raise ValueError("فایل اکسل، فایل فتوشاپ و پوشه‌ی مقصد الزامی است.")
            for sheet_settings in settings.sheets:
                if sheet_settings.psd_path and not Path(sheet_settings.psd_path).exists():
                    candidate = Path(settings.psd_path).parent / sheet_settings.psd_path
                    if candidate.exists():
                        sheet_settings.psd_path = str(candidate)
                    else:
                        raise ValueError(f"قالب شیت «{sheet_settings.name}» پیدا نشد: {sheet_settings.psd_path}")
            runner = BatchRunner(settings)
            self.runner = runner
            try:
                total = 0
                for sheet_settings in _load_sheet_totals(settings):
                    total += sheet_settings
            except Exception:
                total = 0
            self.status = {"state": "running", "done": 0, "total": total, "started": time.time()}

            def progress(payload: dict) -> None:
                with self.lock:
                    self.status.update(payload)
                    self.status["state"] = "running"
                    self.status["started"] = self.started or time.time()

            def work() -> None:
                try:
                    result = runner.run(progress_cb=progress)
                    with self.lock:
                        self.status = {
                            "state": "done" if not result.get("stopped") else "stopped",
                            "done": result.get("done", 0),
                            "total": result.get("total", 0),
                            "errors": result.get("errors", []),
                            "log": result.get("log", []),
                            "out_dir": result.get("out_dir"),
                            "elapsed": result.get("elapsed"),
                            "produced_count": len(result.get("produced", [])),
                        }
                except Exception as exc:  # pragma: no cover
                    with self.lock:
                        self.status = {
                            "state": "error",
                            "done": getattr(runner, "done", 0),
                            "total": getattr(runner, "total", 0),
                            "error": str(exc),
                            "trace": traceback.format_exc(limit=4),
                            "log": getattr(runner, "log", []),
                        }

            self.started = time.time()
            self.thread = threading.Thread(target=work, daemon=True)
            self.thread.start()
            return {"ok": True, "total": total}

    def poll(self) -> dict:
        with self.lock:
            status = dict(self.status)
        if self.runner is not None and status.get("state") == "running":
            status["log"] = self.runner.log[-30:]
        return status

    def stop(self) -> dict:
        if self.runner is not None:
            self.runner.stop_flag.set()
        return {"ok": True}


JOB = JobState()


# ------------------------------------------------------------ انتخاب مسیر


def pick_path(mode: str, title: str = "", extensions: list[str] | None = None) -> dict:
    """باز کردن پنجره‌ی انتخاب فایل/پوشه با tkinter (در سمت سرور)."""
    script = f"""
import sys, tkinter as tk
from tkinter import filedialog
root = tk.Tk(); root.withdraw(); root.attributes('-topmost', True)
mode = {mode!r}
if mode == 'dir':
    path = filedialog.askdirectory(title={title!r})
else:
    types = [("همه فایل‌ها", "*.*")]
    exts = {extensions or []!r}
    if exts:
        types = [(ext.upper().lstrip('.'), '*' + ext) for ext in exts] + types
    path = filedialog.askopenfilename(title={title!r}, filetypes=types)
print(path or "")
"""
    try:
        result = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True,
            text=True,
            timeout=300,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0,
        )
        path = (result.stdout or "").strip().splitlines()[-1] if result.stdout.strip() else ""
        return {"ok": True, "path": path}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def browse(path: str) -> dict:
    """فهرست زیرپوشه‌ها برای پیمایش دستی."""
    if not path:
        if os.name == "nt":
            import string

            drives = [f"{letter}:\\" for letter in string.ascii_uppercase if Path(f"{letter}:\\").exists()]
            return {"ok": True, "path": "", "parent": None, "dirs": drives, "files": []}
        path = str(Path.home())
    target = Path(path)
    if target.is_file():
        target = target.parent
    if not target.exists():
        return {"ok": False, "error": "مسیر وجود ندارد."}
    try:
        children = sorted(target.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
    except PermissionError:
        return {"ok": False, "error": "دسترسی به این مسیر وجود ندارد."}
    dirs = [str(p) for p in children if p.is_dir()]
    allowed = {".psd", ".psb", ".xlsx", ".xlsm", ".csv", ".ttf", ".otf", ".ttc"}
    files = [str(p) for p in children if p.is_file() and p.suffix.lower() in allowed]
    return {"ok": True, "path": str(target), "parent": str(target.parent) if target.parent != target else None, "dirs": dirs, "files": files}


def _load_sheet_totals(settings: JobSettings) -> list[int]:
    """تعداد ردیف‌های قابل تولید هر شیت (برای نمایش درصد پیشرفت)."""
    sheets = read_sheets(settings.excel_path, header_row=settings.header_row)
    by_name = {s.name: s for s in sheets}
    counts = []
    for sheet_settings in settings.sheets:
        if not sheet_settings.enabled:
            continue
        sheet = by_name.get(sheet_settings.name)
        if sheet is None:
            continue
        start = max(0, (sheet_settings.row_from or 1) - 1)
        end = min(sheet.row_count, sheet_settings.row_to or sheet.row_count)
        counts.append(max(0, end - start))
    return counts


def open_folder(path: str) -> dict:
    try:
        target = Path(path)
        if not target.exists():
            target = target.parent
        if os.name == "nt":
            os.startfile(str(target))  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(target)])
        else:
            subprocess.Popen(["xdg-open", str(target)])
        return {"ok": True}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def add_font(source_path: str) -> dict:
    """کپی یک فایل فونت به پوشه‌ی fonts برنامه تا در فهرست فونت‌ها بیاید."""
    from engine.fonts import APP_FONT_DIR

    source = Path(source_path)
    if not source.exists() or source.suffix.lower() not in {".ttf", ".otf", ".ttc", ".otc"}:
        return {"ok": False, "error": "فایل فونت معتبر نیست."}
    target_dir = paths.font_dir()
    target_dir.mkdir(parents=True, exist_ok=True)
    destination = target_dir / source.name
    try:
        if str(source.resolve()) != str(destination.resolve()):
            shutil.copy2(source, destination)
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
    return {"ok": True, "path": str(destination), "name": source.name}


def fonts_payload(query: str = "", force: bool = False) -> dict:
    lib = library()
    lib.load(force=force)
    families = sorted({entry.family for entry in lib.fonts()}, key=lambda s: s.lower())
    if query:
        q = query.lower()
        families = [f for f in families if q in f.lower()]
    start_time = getattr(lib, "_load_started", 0)
    return {"ok": True, "count": len(families), "fonts": families[:400], "indexing": bool(start_time and not lib._loaded)}


# -------------------------------------------------------------- HTTP


class Handler(BaseHTTPRequestHandler):
    server_version = "PsdBatchGen/1.0"

    def log_message(self, fmt: str, *args) -> None:  # کم‌کردن شلوغی لاگ
        if "/api/status" in (self.path or ""):
            return
        sys.stderr.write("%s - %s\n" % (time.strftime("%H:%M:%S"), fmt % args))

    # ------------------------------------------------------------ ابزار
    def _send_json(self, payload: dict, code: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_file(self, path: Path) -> None:
        if not path.exists() or not path.is_file():
            self._send_json({"ok": False, "error": "فایل پیدا نشد."}, 404)
            return
        content_types = {
            ".html": "text/html; charset=utf-8",
            ".js": "application/javascript; charset=utf-8",
            ".css": "text/css; charset=utf-8",
            ".json": "application/json; charset=utf-8",
            ".svg": "image/svg+xml",
            ".png": "image/png",
            ".ico": "image/x-icon",
        }
        data = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_types.get(path.suffix.lower(), "application/octet-stream"))
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return {}
        raw = self.rfile.read(length)
        try:
            return json.loads(raw.decode("utf-8"))
        except Exception:
            return {}

    # -------------------------------------------------------------- GET
    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        route = parsed.path
        query = parse_qs(parsed.query)

        try:
            if route in ("/", "/index.html"):
                self._send_file(WEB_DIR / "index.html")
            elif route.startswith("/static/"):
                self._send_file(WEB_DIR / route.replace("/static/", "", 1))
            elif route == "/api/settings":
                if SETTINGS_FILE.exists():
                    self._send_json({"ok": True, "settings": json.loads(SETTINGS_FILE.read_text("utf-8"))})
                else:
                    self._send_json({"ok": True, "settings": None})
            elif route == "/api/browse":
                self._send_json(browse((query.get("path") or [""])[0]))
            elif route == "/api/pick":
                self._send_json(
                    pick_path(
                        (query.get("mode") or ["file"])[0],
                        (query.get("title") or ["انتخاب"])[0],
                        [e for e in (query.get("ext") or [""])[0].split(",") if e],
                    )
                )
            elif route == "/api/status":
                self._send_json(JOB.poll())
            elif route == "/api/fonts":
                self._send_json(fonts_payload((query.get("q") or [""])[0], bool(query.get("force"))))
            elif route == "/api/fonts/refresh":
                self._send_json(fonts_payload("", force=True))
            elif route == "/api/open":
                self._send_json(open_folder((query.get("path") or [""])[0]))
            else:
                self._send_json({"ok": False, "error": "مسیر یافت نشد."}, 404)
        except Exception as exc:  # pragma: no cover
            self._send_json({"ok": False, "error": str(exc), "trace": traceback.format_exc(limit=4)}, 500)

    # ------------------------------------------------------------- POST
    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        route = parsed.path
        data = self._read_json()
        try:
            if route == "/api/analyze":
                self._send_json(analyze(data))
            elif route == "/api/preview":
                self._send_json(preview(data))
            elif route == "/api/start":
                self._send_json(JOB.start(data))
            elif route == "/api/stop":
                self._send_json(JOB.stop())
            elif route == "/api/save-settings":
                SETTINGS_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), "utf-8")
                self._send_json({"ok": True, "path": str(SETTINGS_FILE)})
            elif route == "/api/fonts/refresh":
                self._send_json(fonts_payload("", force=True))
            elif route == "/api/fonts/add":
                result = add_font(data.get("path", ""))
                if result.get("ok"):
                    fonts_payload("", force=True)
                self._send_json(result)
            else:
                self._send_json({"ok": False, "error": "مسیر یافت نشد."}, 404)
        except Exception as exc:
            self._send_json({"ok": False, "error": str(exc), "trace": traceback.format_exc(limit=6)}, 500)


def build_server(host: str = "127.0.0.1", port: int = 8756) -> ThreadingHTTPServer:
    """سرور محلی را می‌سازد (برای اجرای معمولی و نسخه‌ی ویندوزی)."""
    return ThreadingHTTPServer((host, port), Handler)


def main() -> None:
    parser = argparse.ArgumentParser(description="تولید انبوه تصویر از قالب فتوشاپ")
    parser.add_argument("--port", type=int, default=int(os.environ.get("PSD_BATCH_PORT", 8756)))
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()

    url = f"http://{args.host}:{args.port}/"
    httpd = build_server(args.host, args.port)
    print("=" * 64)
    print("  برنامه‌ی تولید انبوه تصویر از قالب فتوشاپ")
    print(f"  آدرس برنامه در مرورگر: {url}")
    print("  برای بستن برنامه، این پنجره را ببندید یا Ctrl+C بزنید.")
    print("=" * 64)

    if not args.no_browser:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nبرنامه بسته شد.")


if __name__ == "__main__":
    main()
