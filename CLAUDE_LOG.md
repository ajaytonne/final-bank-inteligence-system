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

## 2026-11-04 — Change 4: financial summary, automatic categories, search & filter

**Why:** requested features. Mapping to this app: a deposit is Income and a withdrawal is an Expense; "Add row" is the way a
transaction is added, so the category logic hooks into it.

**New files**
- `frontend/src/components/FinancialSummary.jsx`: Total Income / Total Expenses / Savings cards + top expense category.
- `frontend/src/components/TransactionFilters.jsx`: Search & Filter box and the "Showing X of Y" count.

**Changed files (small edits)**
- `backend/app/schemas.py`: `Category` type and `ReviewedTransaction.category` (default "Other", so old saved rows still load).
- `frontend/src/utils/review.js`: `CATEGORIES`, `detectCategory`, `rowType`, `filterRows`, `summarize`, `formatRupees`; category kept in
  review state and sent in the save payload.
- `frontend/src/App.jsx`: filter state, category handlers, the two new components in the page.
- `frontend/src/components/TransactionsTable.jsx`: Category dropdown + Income/Expense label columns, "No transactions found" message,
  narrower minimum column widths so the table still fits a 1440px screen.
- `frontend/src/components/SavedStatements.jsx`: Category column in the saved-statement view.
- Tests: `backend/tests/test_api.py` (+4), `frontend/src/__tests__/review.test.js` and `App.test.jsx` (+37). README updated.

**Not changed:** API routes, DB table layout (category lives inside the saved JSON), extraction pipeline, theme, existing tests.
**Not added:** `GET /api/summary`, `GET/POST/PUT /api/transactions`: transactions here only exist inside a statement, which is
already saved through `POST /api/statements` (now with category). The summary and filters run on the statement under review.

**Tested:** backend 115 passed, frontend 55 passed, production build OK, and the real app (headless Chrome) with
`statement_text.pdf`: summary figures, categories, every filter, Clear Filters and manual category override, no console errors.
**Unsure:** the "Statement analysis" panel in `SummaryBar.jsx` still uses its own older category names (e.g. Transfers, Fees); left as is.

## 2026-11-20 — Change 5: automatic merchant identification + multi-bank reconciliation

**Differences between the request and this project (handled as follows)**
- No SQLAlchemy: the project uses plain `sqlite3`. Kept it; new tables are created with `CREATE TABLE IF NOT EXISTS` (nothing destructive, no migration of
  existing tables; the `statements` table is untouched).
- No login/authentication and no page routing: so there is no user_id; navigation is a new tab bar (Statement review | Reconciliation).
- Transactions have no ids of their own (they live inside a saved statement's JSON). A transaction is identified by (statement id, row number); result rows keep a
  copy of date/description/reference/amount/direction for display and export.
- Merchant categories (Shopping, Food, Groceries, Transport, Utilities, Entertainment, Banking, Other) are a separate field from the transaction Category added in Change 4.
- The approval step after the plan was skipped because you asked for the finished zip directly.

**New backend files:** `app/services/merchant_identifier.py`, `app/services/reconciliation_engine.py`, `app/services/recon_store.py`,
`app/routes_merchants.py`, `app/routes_reconciliation.py`; tests `tests/test_merchant_identifier.py`, `tests/test_reconciliation_engine.py`, `tests/test_reconciliation_api.py`.
**New frontend files:** `components/MerchantCorrectionDialog.jsx`, `components/BankAccounts.jsx`, `components/Reconciliation.jsx`; test `__tests__/Reconciliation.test.jsx`.
**Changed (small edits):** `app/main.py` (include the two routers, allow PUT in CORS), `app/schemas.py` (new schemas appended), `frontend/src/api/client.js` (new calls),
`utils/review.js` (MERCHANT_CATEGORIES), `App.jsx` (tabs, merchant lookup), `TransactionsTable.jsx` (Merchant column), `__tests__/App.test.jsx` (mock + tests), README, this log.

**Tested:** backend 211 passed (was 115), frontend 70 passed (was 55), production build OK, and the real app in headless Chrome: merchants for a real extracted statement, saved
correction reused, accounts, internal reconciliation of a repeated upload (all 14 matched, "second upload" note), inter-bank SBI to HDFC rent transfer matched on its reference
(1 day timing difference), confirmation removed it from the combined totals, CSV export, no console errors.
**Limitations:** matching is rule based; same-amount same-day transactions go to manual review by design. Narrations that carry a UTR inside the text (not in the reference column) are
not read as references. The merchant dictionary covers common Indian brands only and is easy to extend. Split transactions (one debit = several credits) are not supported. Reconciliation
reads the saved statements, so statements must be reviewed and saved first. Not tested on real bank statements, only the sample/dummy ones.



## 2026-11-20 — Change 6: duplicate / overlap warnings + audit trail (History tab)

**What:** (1) before saving, warn about a duplicate statement, an overlapping period for the same account, or repeated rows; (2) an audit trail of saves, edited fields and deletes.
**Decisions:** warnings never block saving (the person decides); duplicates are matched by account last 4 digits (+ bank when both known) and an order-independent fingerprint of
(date, description, amounts). Edited fields are computed in the browser (value vs. extracted original) and sent as `changes` with the save request; the server writes them to the audit
log and does not store them in the statement (so old and new statements look the same). Rows deleted by the reviewer before saving cannot be listed (the original is gone from the screen).
**New backend files:** `services/audit_log.py`, `services/duplicate_check.py`, `routes_audit.py`; test `tests/test_audit_and_duplicates.py`.
**New frontend files:** `components/SaveWarningsDialog.jsx`, `components/AuditHistory.jsx`.
**Changed (small edits):** `main.py` (log on save/delete, include router), `schemas.py` (FieldChange, AuditEntry, StatementWarning, optional `changes`), `services/storage.py` (leave `changes` out of
the stored payload), `api/client.js`, `utils/review.js` (`buildChanges`), `App.jsx` (check before save, History tab), tests, README, this log.
**Tested:** backend 224 passed (was 211), frontend 80 passed (was 70), production build OK.
**Limitations:** no login, so the log does not say WHO did something. Statements saved before this change have no history. Duplicate detection needs an account number on both statements.


## 2026-11-21 — Change 7: Statement Analyser as a module

**Request:** the CTO assigned "Statement Analyser to be made as a module" without naming the host application, so this builds the generic version: a Python module, a React component and a
one-page guide (MODULE.md). Decisions: the Python package `app` was renamed `statement_analyser` (every import changed mechanically; a module called `app` would clash with the host's own `app`);
`mount()` uses Starlette's sub-application mount, so the host's routes are untouched; the React component takes `apiBase` at run time and does not bundle React or MUI.
**New files:** `backend/statement_analyser/module.py` (`analyse`, `create_app`, `mount`), `backend/pyproject.toml`, `backend/tests/test_module.py`, `frontend/src/module.jsx`,
`frontend/vite.module.config.js`, `frontend/src/__tests__/module.test.jsx`, `examples/host_app.py`, `examples/host_page.jsx`, `MODULE.md`.
**Changed:** `backend/app/` -> `backend/statement_analyser/` (imports, Dockerfile CMD, README paths), `statement_analyser/__init__.py` (exports), `api/client.js` (`setApiBase`),
`App.jsx` (optional `title`, `embedded` props; behaviour unchanged by default), `package.json` (`build:module`).
**Tested:** backend 235 passed (was 224), frontend 84 passed (was 80), standalone build and module build OK. Real check: installed the package with pip, ran a separate host app
that mounts it, and extracted a sample statement through `/statement-analyser/api/extract` (14 transactions).
**Not done (needs the host's decisions):** user accounts and per-user data, a non-SQLite database, encryption/retention. Not tried inside a real host React app or a non-FastAPI backend.


## 2026-11-21 — Change 8: analysis API, analytics, tamper checks, bank detection (towards the CTO's "market level" requirements)

**Why:** the CTO wants the module to match market tools: all banks, OCR, API-based analysis. This builds what does not depend on getting real bank statements.
**Added:** `services/analytics.py` (balances, monthly view, salary, EMI/NACH, bounces, cash, circular transfers), `services/tamper_check.py` (PDF file-trail warning signs),
`services/bank_profiles.py` (bank from the IFSC code; ~40 banks), `services/analysis.py` (one call: extraction + bank + analytics + tamper + flags), `services/job_store.py` and
`routes_analysis.py` (`POST /api/analysis`, `GET /api/statements/{id}/analytics`, asynchronous `/api/v1/analyses` with `X-API-Key` and an allow-listed https webhook), password protected PDFs
(`password` argument), `analyse_full()` in the module, an "Analysis" tab (`Analysis.jsx`, `AnalysisResult.jsx`).
**Changed (small edits):** `config.py` (`API_KEYS`, `WEBHOOK_ALLOWED_HOSTS`), `text_extraction.extract_pdf` and `pipeline.run_extraction` (optional password), `main.py` (router), `module.py`, `__init__.py`,
`api/client.js`, `App.jsx` (tab), README, MODULE.md.
**Tested:** backend 287 passed (was 235), frontend 91 passed (was 84), both builds OK; real server with `API_KEYS` set: 401 without the key, job done with it; the Analysis tab in headless Chrome with a real
upload, no console errors, no horizontal overflow.
**Decisions:** the v1 API is protected by keys but the screens' endpoints are not (the host is expected to protect the rest, see MODULE.md). A webhook host must be on an allow-list and https, and redirects are not
followed. Tamper flags and every analytics finding are indicators for a person, not verdicts. Salary, EMI, bounce and cash rules are keyword and repetition rules, tuned on dummy data only.
**NOT done (needs data or partners):** per-bank layout tuning and an accuracy figure per bank (needs real masked statements; the bank is now NAMED but the reader is still generic); Account Aggregator integration
(needs an AA/FIU partner and consent flow); OCR accuracy work (needs scanned samples); users/tenants, encryption, a real job queue.

**Fix (2026-11-23):** bank detection by name searched the whole statement, so a narration such as "NEFT TRANSFER TO ICICI 5678" made an HDFC statement show as ICICI Bank. It now reads only the title block above the transaction table (`header_text` in `bank_profiles.py`); regression test added. Backend 287 passed.


## 2026-11-23 — Change 9: LIST branding and UI refresh

**Request:** make the UI better and put the LIST logo (supplied as a small screenshot) on the background, since the module is for LIST software.
**What:** the logo was made transparent (dark and white versions, `src/assets/`), shown in a new white header with the product name, and as a faint fixed background mark (`components/Brand.jsx`).
Theme refreshed (`theme.js`: ink + teal accent, softer cards that let the mark show through, rounded tabs and buttons); Inter font; favicon; page title "Statement Analyser | LIST".
The tabs scroll on a phone. The logo is inlined in the code (`?inline`) so it works inside the module build too, where the mark stays inside the module's own box.
**Changed:** `theme.js`, `App.jsx` (header, tabs, background), `index.html`, new `components/Brand.jsx`, `assets/*.png`, `public/favicon.png`, `__tests__/Branding.test.jsx`, README.
**Tested:** frontend 96 passed (was 91); both builds OK; real browser at 1440 px and 390 px: no horizontal overflow, no app errors (the only console error is the Google font failing to load in the offline sandbox).
**Limit:** the logo was traced from a 133 px screenshot, so edges are slightly soft at large sizes; the original vector file would be sharper. LIST's brand colours are not known, so the accent is a neutral teal: change `BRAND` in `theme.js`.
