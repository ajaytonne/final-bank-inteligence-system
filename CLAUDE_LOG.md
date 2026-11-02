# CLAUDE_LOG

## 2026-11-02 — Change 1: find Tesseract even when it is not on PATH

**Files touched:** `backend/app/services/text_extraction.py` only.

**Why:** On Windows the Tesseract installer puts `tesseract.exe` in
`C:\Program Files\Tesseract-OCR` and does NOT add it to PATH by default. The old
`tesseract_available()` only used `shutil.which("tesseract")`, so it returned False,
and `extract_pdf` then skipped scanned pages with a warning (empty result).

**What changed**
- New `find_tesseract()`: checks `TESSERACT_CMD` env var, then PATH, then the default Windows install folders.
- `tesseract_available()` now sets `pytesseract.pytesseract.tesseract_cmd` to the path it found.
- `OCRUnavailableError` message is clearer ("Tesseract not found. ... set TESSERACT_CMD ...").

**Not changed:** folder structure, file names, API routes, DB models, config.py, Dockerfile.

**Tested (Linux sandbox, Tesseract 5.3.4):** normal PATH -> found; PATH removed + `TESSERACT_CMD` -> found;
PATH removed, no env -> `False` + clear error from `extract_image`. Existing suite: 111 passed.

**Assumptions / unsure**
- Not tested on real Windows; the Windows default paths are the installer's documented defaults.
- Your symptom text and "fails on" fields were still template placeholders, so this is the most likely cause from code reading, not a confirmed diagnosis.
- Known gap (planned for a later change): for PDFs, a missing Tesseract still only adds a warning instead of raising an error.
- Already present in the project before this change: 300 DPI PyMuPDF render, grayscale/autocontrast/deskew, `--psm 6`, per-word confidence via `image_to_data`, Tesseract in the Dockerfile.

## 2026-11-02 — Change 2: clear error for scanned PDFs + Windows installer script

**Files touched:** `backend/app/services/text_extraction.py` (extract_pdf), new `backend/scripts/setup_tesseract_windows.ps1`.

**Why:** User's laptop showed "Tesseract not found" (Tesseract genuinely not installed). Scanned PDFs would
still return an empty result silently in that situation.

**What changed**
- `extract_pdf` raises `OCRUnavailableError` (-> HTTP 503, same message as images) only when EVERY page needs OCR
  and Tesseract is missing. A text PDF with one near-empty page still works (warning only).
- `setup_tesseract_windows.ps1`: installs Tesseract with winget and sets `TESSERACT_CMD`. Extra file, scripts/ folder already existed.

**Tested (Linux):** scanned PDF without Tesseract -> clear error; text PDF without Tesseract -> OK; full suite passes.
**Unsure:** PowerShell script not run on real Windows (no PowerShell here). winget must be available (Windows 10 21H1+/11).

## 2026-11-02 — Change 3: pip-only OCR fallback (no system install needed)

**Why:** User still saw "Page N has little text and OCR is unavailable; page skipped" -> Tesseract is not installed on their
Windows laptop (and that message is from the pre-change-2 code, i.e. an older backend was still running).

**Files touched**
- `backend/app/services/text_extraction.py`: `rapidocr_available()`, `ocr_available()`, `rapid_image_words()`;
  `ocr_image_words` and `extract_pdf` fall back to RapidOCR only when Tesseract is missing. Tesseract stays first choice.
- `backend/app/main.py` (required): `/api/health` now reports `ocr_available()` so the UI "OCR ready" chip is true with either engine.
  Field name `tesseract_available` and the route are unchanged.
- `backend/requirements.txt` (required): added `rapidocr-onnxruntime>=1.2.3`.
- `backend/tests/test_api.py`: the "OCR unavailable -> 503" test now also disables the fallback.
- `README.md`: prerequisites note.

**Tested (Linux, simulated no-Tesseract):** scanned PDF 14 rows, balance passed; image 8 rows, balance passed; text PDF unchanged.
With Tesseract present, results unchanged. 111 tests pass.

**Assumptions / unsure**
- RapidOCR returns text lines, so words are split by character share; some descriptions lose spaces
  (e.g. "SALARYCREDITACMEPVTLTD"). Amounts/dates were correct on the samples.
- Not tested on real Windows. First OCR call downloads nothing (models ship in the wheel) but loads slowly (~10-15 s).
- Docker image gets larger (onnxruntime + OpenCV). Tesseract is still installed there and used first.
- Low-res/cropped real-world screenshots (e.g. 624px wide with cut-off Balance column) are still unreliable with either engine.
