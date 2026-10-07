# -*- mode: python ; coding: utf-8 -*-
"""
فایل ساخت نسخه‌ی ویندوزی با PyInstaller — بدون پنجره‌ی CMD و با آیکون.

ساخت معمولی (پوشه‌ی ماژولار؛ پیشنهادی):

    pyinstaller packaging/windows.spec --noconfirm --clean

ساخت تک‌فایلی (یک exe تنها):

    set PSD_BATCH_ONEFILE=1        (ویندوز)   /   PSD_BATCH_ONEFILE=1 (لینوکس/مک)
    pyinstaller packaging/windows.spec --noconfirm --clean

خروجی در پوشه‌ی dist/ ساخته می‌شود. راهنمای کامل: docs/BUILD-WINDOWS.md

نکته‌ی مهم ۱: در فایل‌های spec متغیر `__file__` وجود ندارد؛ PyInstaller متغیر
`SPECPATH` (مسیر پوشه‌ی همین فایل) را در اختیار spec می‌گذارد.

نکته‌ی مهم ۲: هر چیزی که این فایل «چاپ» می‌کند باید **فقط ASCII** باشد؛ چون روی ویندوز
خروجی کنسول با کدگذاری cp1252 باز می‌شود و متن فارسی باعث خطای
UnicodeEncodeError: 'charmap' codec can't encode characters می‌شود.
(کامنت‌ها می‌توانند فارسی بمانند؛ فقط رشته‌های چاپ‌شده باید انگلیسی باشند.)
"""

import os
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_submodules

# ------------------------------------------------------------ مسیرهای پروژه
SPEC_DIR = Path(SPECPATH).resolve()  # noqa: F821  (توسط PyInstaller تعریف می‌شود)
ROOT = SPEC_DIR if (SPEC_DIR / "server.py").exists() else SPEC_DIR.parent

if not (ROOT / "server.py").exists():
    raise SystemExit(
        "[windows.spec] Project files not found.\n"
        f"[windows.spec] spec folder: {SPEC_DIR}\n"
        "[windows.spec] Put this file in the packaging/ folder of the project and run:\n"
        "    pyinstaller packaging/windows.spec"
    )

print(f"[windows.spec] project root: {ROOT}")

APP_NAME = "PSD-Batch-Generator"
ICON = SPEC_DIR / "icon.ico"
VERSION_FILE = SPEC_DIR / "version_info.txt"
ONE_FILE = os.environ.get("PSD_BATCH_ONEFILE", "0") == "1"

# ---------------------------------------------------------------- داده‌ها
datas = [
    (str(ROOT / "web"), "web"),
    (str(ROOT / "fonts"), "fonts"),
    (str(ROOT / "docs"), "docs"),
    (str(ROOT / "samples" / "نمونه-اطلاعات.xlsx"), "samples"),
    (str(ROOT / "samples" / "نمونه-قالب.psd"), "samples"),
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
        print(f"[windows.spec] WARNING: collect_all({package}) failed: {exc}")
hiddenimports += collect_submodules("psd_tools")

# بسته‌های سنگین که برنامه به آن‌ها نیازی ندارد.
# (زیرماژول‌های اختیاری psd_tools آن‌ها را به گراف می‌کشند و حجم exe را چند برابر می‌کنند)
excludes = [
    # علمی/داده‌ای — از psd_tools.composite اختیاری
    "scipy", "pandas", "numba", "llvmlite", "matplotlib", "sklearn", "skimage",
    "librosa", "seaborn", "gensim", "xarray", "sympy", "statsmodels", "networkx",
    "lxml", "yaml", "pytz", "dateutil",
    # ابزارهای توسعه و تست
    "pytest", "playwright", "IPython", "jupyter", "notebook", "sphinx", "setuptools",
    # فریم‌ورک‌های گرافیکی دیگر (ما فقط tkinter را لازم داریم)
    "PyQt5", "PyQt6", "PySide2", "PySide6", "wx", "gi",
]
print("[windows.spec] excluded packages:", ", ".join(excludes))

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
