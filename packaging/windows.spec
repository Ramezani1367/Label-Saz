# -*- mode: python ; coding: utf-8 -*-
"""
فایل ساخت نسخه‌ی ویندوزی با PyInstaller — بدون پنجره‌ی CMD و با آیکون.

ساخت معمولی (پوشه‌ی ماژولار؛ پیشنهادی):

    pyinstaller packaging/windows.spec --noconfirm

ساخت تک‌فایلی (یک exe تنها):

    set PSD_BATCH_ONEFILE=1        (ویندوز)   /   PSD_BATCH_ONEFILE=1 (لینوکس/مک)
    pyinstaller packaging/windows.spec --noconfirm

خروجی در پوشه‌ی dist/ ساخته می‌شود. راهنمای کامل: docs/BUILD-WINDOWS.md
"""

import os
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_submodules

SPEC_DIR = Path(globals().get("SPECPATH", Path(__file__).resolve().parent)).resolve()
ROOT = SPEC_DIR.parent if (SPEC_DIR / "windows.spec").exists() else SPEC_DIR

APP_NAME = "PSD-Batch-Generator"
ICON = SPEC_DIR / "icon.ico"
VERSION_FILE = SPEC_DIR / "version_info.txt"
ONE_FILE = os.environ.get("PSD_BATCH_ONEFILE", "0") == "1"

# ---------------------------------------------------------------- داده‌ها
datas = [
    (str(ROOT / "web"), "web"),
    (str(ROOT / "fonts"), "fonts"),
    (str(ROOT / "samples"), "samples"),
    (str(ROOT / "docs"), "docs"),
    (str(SPEC_DIR / "icon.ico"), "packaging"),
    (str(SPEC_DIR / "icon.png"), "packaging"),
    (str(ROOT / "README.md"), "."),
]
binaries = []
hiddenimports = ["tkinter", "tkinter.ttk", "tkinter.messagebox", "engine.paths"]

for optional in (ROOT / "LICENSE",):
    if optional.exists():
        datas.append((str(optional), "."))

# کتابخانه‌هایی که import پویا دارند و باید کامل جمع‌آوری شوند
for package in ("psd_tools", "PIL", "numpy", "openpyxl"):
    try:
        package_datas, package_binaries, package_hidden = collect_all(package)
        datas += package_datas
        binaries += package_binaries
        hiddenimports += package_hidden
    except Exception as exc:  # pragma: no cover - فقط برای اطمینان
        print(f"! collect_all({package}) ناموفق بود: {exc}")
hiddenimports += collect_submodules("psd_tools")

excludes = ["matplotlib", "pytest", "playwright", "IPython", "PyQt5", "PySide2", "PySide6", "notebook"]

# ------------------------------------------------------------------ ساخت
a = Analysis(
    [str(ROOT / "windows_app.pyw")],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

common = dict(
    name=APP_NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,          # ← پنجره‌ی CMD باز نمی‌شود
    disable_windowed_traceback=False,
    icon=str(ICON) if ICON.exists() else None,
    version=str(VERSION_FILE) if VERSION_FILE.exists() else None,
)

if ONE_FILE:
    exe = EXE(pyz, a.scripts, a.binaries, a.datas, [], **common)
else:
    exe = EXE(pyz, a.scripts, [], exclude_binaries=True, **common)
    coll = COLLECT(
        exe,
        a.binaries,
        a.datas,
        strip=False,
        upx=False,
        upx_exclude=[],
        name=APP_NAME,
    )
