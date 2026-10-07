# PSD Batch Generator

A small **local web app** that takes one **Photoshop file (PSD)** and one **Excel workbook**
and produces one output file per row, replacing the text of Photoshop *type layers* with the
values of the matching Excel columns.

Typical use cases: business cards, product labels, letterheads, ID cards, certificates,
price tags — anything where the text changes per item.

## Features

- Placeholders inside the Photoshop text itself: `{{Column name}}` — e.g. `Code: {{Product code}}`.
- Multi-sheet Excel: every sheet becomes a folder named after the sheet, with its own
  file-naming (two columns + separator + prefix/suffix), row range and optional template.
- Output formats: **PNG / JPG / WEBP** and **PDF** in three modes:
  - `sheet` — one merged PDF per folder (per sheet)
  - `all` — one merged PDF containing every sheet
  - `each` — one PDF per row
  - plus an option to also save the per-row PDFs next to a merged PDF.
- Optional CSV index of every produced file, live progress, stop button, preview of a single row.
- Persian/RTL UI, light tabbed HTML interface (5 steps), everything runs offline.
- Windows build: single-click **exe without a console window**, with an application icon
  (see `docs/BUILD-WINDOWS.md` and `.github/workflows/build-windows.yml`).

## Quick start (any OS)

```bash
pip install -r requirements.txt
python run.py            # opens http://127.0.0.1:8756 in your browser
```

Windows users can double-click `run.bat` (or `run_windows.bat` for a no-console start).

## Build the Windows app

Push the repository to GitHub → the **build-windows** Actions workflow produces two artifacts
(modular folder build and a single-file exe). Locally: `packaging/build_windows.bat`.

## Project layout

```
server.py       local HTTP server + JSON APIs
engine/         Excel / PSD text / fonts / rendering / batch runner
web/            HTML+CSS+JS user interface (Persian, RTL)
packaging/      icon + PyInstaller spec + Windows build script
tests/          smoke tests (python tests/smoke_test.py)
tools/          sample generator, preview builder, screenshot tool
docs/           handoff notes, Windows build guide, this file
```

## Tests

```bash
python tools/make_sample.py
python tests/smoke_test.py
```

## License

MIT — see `LICENSE`.
