# Bank Statement Intelligence System — AI-Powered Document Extraction

Upload a **dummy** bank statement (PDF or image) → get structured JSON (header + transactions) with
heuristic review scores → review and correct in a React UI → save the reviewed data.

The system assists a human reviewer; it never invents financial values. Missing or uncertain
values are returned as `null` / flagged with `needs_review: true`. Review fields include bank,
branch, account type, IFSC and effective date when those values appear in the statement. The
summary panel also shows rule-based income, expenses, spending categories, monthly totals and
possible duplicate or unusually large debit candidates.

```
bank-statement-ai/
├── backend/                  FastAPI + PyMuPDF + Tesseract (+ optional Ollama)
│   ├── statement_analyser/
│   │   ├── main.py           API routes (statements, extract, health)
│   │   ├── routes_merchants.py        merchant identification + saved corrections API
│   │   ├── routes_reconciliation.py   bank accounts + reconciliation API
│   │   ├── config.py         env settings
│   │   ├── schemas.py        Pydantic models (extraction + reviewed payload)
│   │   └── services/
│   │       ├── file_validation.py  extension, size, magic-byte checks
│   │       ├── text_extraction.py  PDF text → OCR fallback (deskew, rule removal)
│   │       ├── normalize.py        date / amount / account-mask parsing
│   │       ├── parser.py           header fields + table/positional row parsing
│   │       ├── validation.py       running-balance check, side inference
│   │       ├── llm.py              optional Ollama header fill (grounded only)
│   │       ├── pipeline.py         orchestration + confidence → review flags
│   │       ├── storage.py          SQLite store for reviewed statements
│   │       ├── merchant_identifier.py  merchant rules + saved corrections (own table)
│   │       ├── reconciliation_engine.py  pure matching rules, summary, consolidated totals
│   │       └── recon_store.py      bank accounts + reconciliation results (own tables)
│   ├── scripts/sample_data.py      synthetic statement generator
│   ├── samples/                    6 ready-made dummy statements
│   └── tests/                      287 pytest tests
└── frontend/                 React 18 + Vite + MUI
    └── src/
        ├── App.jsx                  page + review state
        ├── api/client.js            fetch wrapper
        ├── utils/review.js          state mapping, validation, live balance check
        ├── components/              Upload, Summary, Financial summary, Header card, Filters, Transactions table, Saved list
        └── __tests__/               96 Vitest + Testing Library tests
```

> **Using this inside another application?** See [MODULE.md](MODULE.md): `analyse()`, `mount()` and a `<StatementAnalyser />` component.

## 1. Prerequisites

| Tool | Version | Notes |
|---|---|---|
| Python | 3.10+ | tested on 3.13 |
| Node.js | 22.22+ recommended | Vite build works on supported LTS releases; current test dependencies need a recent Node 22 release |
| Tesseract OCR | 4/5 | preferred for scanned PDFs and images; if missing, the pip package `rapidocr-onnxruntime` (in requirements.txt) is used as a fallback |
| Ollama | optional | app works fully without it |

Install Tesseract:
- **Ubuntu/Debian:** `sudo apt install tesseract-ocr`
- **macOS:** `brew install tesseract`
- **Windows:** install from the UB-Mannheim build, then add `C:\Program Files\Tesseract-OCR` to `PATH`.

## 2. Run the backend

```bash
cd backend
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
cp .env.example .env               # optional; env vars are read from the shell
uvicorn statement_analyser.main:app --reload --port 8000
```

API docs: http://localhost:8000/docs

> `config.py` reads plain environment variables. To use `.env`, export them
> (`set -a; source .env; set +a`) or run `uvicorn statement_analyser.main:app --env-file .env`.

## 3. Run the frontend

```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:5173. Vite proxies `/api` to `localhost:8000`.
For a separate API host set `VITE_API_BASE_URL=https://api.example.com` and add the
frontend origin to the backend `CORS_ORIGINS`.

## 4. Tests

```bash
cd backend  && pytest -q      # 287 passed (OCR tests auto-skip if Tesseract missing)
cd frontend && npm test       # 96 passed
cd frontend && npm run build  # production build
```

Regenerate sample files: `cd backend && python -m scripts.sample_data`

| Sample | What it exercises |
|---|---|
| `statement_text.pdf` | clean text PDF, 2 pages, multi-line description |
| `statement_tampered.pdf` | one balance altered → rows 6–7 flagged, balance check fails |
| `statement_full_account_no.pdf` | full account number → system masks to last 4 |
| `statement_no_table_header.pdf` | no column header → positional parsing, sides inferred from balance |
| `statement_scanned.pdf` | image-only PDF with slight skew → OCR path |
| `statement_image.png` | PNG upload → OCR path |

## 5. API

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/health` | Tesseract / Ollama status |
| POST | `/api/extract` | multipart `file` → `ExtractionResult` |
| POST | `/api/statements` | save reviewed data (`ReviewedStatement`) |
| GET | `/api/statements` | list saved |
| GET | `/api/statements/{id}` | get one |
| DELETE | `/api/statements/{id}` | delete |
| POST | `/api/merchants/identify` | `{descriptions: [...]}` → merchant, category, confidence, reason per narration |
| GET / POST | `/api/merchants/mappings` | list/search (`?q=`) and save a merchant correction |
| DELETE | `/api/merchants/mappings/{id}` | forget a correction |
| GET / POST | `/api/bank-accounts` | list / add a bank account (`ownership_confirmed` = "this is mine") |
| PUT | `/api/bank-accounts/{id}` | change name, masked number or ownership |
| GET | `/api/statement-accounts` | which saved statement is linked to which account |
| PUT | `/api/statements/{id}/account` | link (or unlink with `null`) a saved statement to an account |
| POST | `/api/analysis` | upload a file (+ optional `password`): full analysis (bank, analytics, tamper checks, flags) in one response |
| GET | `/api/statements/{id}/analytics` | the same analytics for a saved (reviewed) statement |
| POST / GET / DELETE | `/api/v1/analyses` , `/api/v1/analyses/{id}` | asynchronous API for other systems: submit a file, get a job id, fetch the result; `X-API-Key` when `API_KEYS` is set; optional `callback_url` webhook (https, host in `WEBHOOK_ALLOWED_HOSTS`) |
| POST | `/api/statements/check` | warnings for a statement about to be saved (duplicate, overlapping period, repeated rows); stores nothing |
| GET | `/api/audit?statement_id=` | history: saved, edited fields (old to new), deleted; newest first |
| POST / GET | `/api/reconciliations` | create (`kind` internal / inter_bank, two statement ids, `date_window_days` 0-7) / list |
| POST | `/api/reconciliations/{id}/run` | run the matching once; results are stored |
| GET / DELETE | `/api/reconciliations/{id}` | results + summary / delete the results (statements untouched) |
| POST | `/api/reconciliations/{id}/matches/{mid}/confirm` \| `/reject` | your decision on a pair |
| GET | `/api/reconciliations/{id}/consolidated` | combined income/expenses, leaving out only CONFIRMED own-account transfers |
| GET | `/api/reconciliations/{id}/export` | CSV of every result row |

Error codes on extract: `413` too large, `415` wrong type / spoofed content, `422` unreadable,
encrypted or too many pages, `503` OCR needed but Tesseract missing.

Every extracted field has this shape:

```json
{ "value": "25000.00", "confidence": 0.95, "needs_review": false,
  "source": "pdf_text", "note": null }
```

`source` is one of `pdf_text`, `ocr`, `llm`, `derived`, `none`. Amounts are serialised as
decimal strings to avoid float rounding.

## 6. How extraction works

1. **Validate upload** — extension whitelist, size limit, magic-byte sniffing (a `.pdf` that is
   really a PNG is rejected), filename stripped of paths.
2. **Get words with positions**
   - Text PDF: PyMuPDF `get_text("words")`.
   - A page with fewer than `MIN_TEXT_CHARS` characters is rendered at `OCR_DPI` and OCR'd.
   - OCR preprocessing: grayscale → autocontrast → upscale → **deskew** (projection profile)
     → **remove table rule lines** (they made Tesseract drop the header row in testing) →
     `pytesseract.image_to_data` with per-word confidence.
3. **Rebuild lines and cells** from word coordinates (same code for PDF text and OCR).
4. **Header fields** — label regexes (account holder, account number, statement period,
   opening/closing balance). Full account numbers are masked to the last 4 digits.
5. **Transaction rows**
   - If a column header is found (Date / Narration / Ref / Debit / Credit / Balance and
     synonyms), words are assigned to columns: text columns by left edge, amount columns by
     right edge.
   - Otherwise positional parsing: leading date, trailing amounts, reference pattern.
   - Lines without a date that follow a row are treated as description continuations.
6. **Running-balance validation** — `prev + deposit − withdrawal = balance` for each row.
   Unknown deposit/withdrawal sides are inferred from the balance; swapped columns are
   corrected and noted; mismatches flag the row. Computed closing is compared to the stated one.
7. **Optional Ollama** — only when header fields are still missing. The LLM's answer is
   accepted only if the value literally appears in the document text (grounding check),
   and is always marked `needs_review`. Transactions are never taken from the LLM.
8. **Review flags** — a field needs review if missing (and required), below
   `REVIEW_THRESHOLD`, or sourced from `llm`/`derived`. Raw text sent to the UI has long
   digit runs redacted.

### Confidence score (heuristic, not a probability)

| Signal | Effect |
|---|---|
| PDF text layer | base 0.95 |
| OCR | mean Tesseract word confidence for that field |
| No table header (positional) | × 0.85 |
| Unusual characters in a name | × 0.6 |
| Row passes balance check | + 0.04 (max 0.99) |
| Row fails balance check | × 0.6 |
| Side inferred / columns swapped | lowered and noted |
| LLM value | fixed 0.55 + review |
| Derived opening balance | fixed 0.6 + review |

## 7. Review UI

- Header fields and every transaction cell are editable; editing a flagged item marks it reviewed.
- Rows that need review are highlighted with an issue tooltip and a **Reviewed** checkbox.
- The running balance is **re-checked live** as you edit.
- Tabs: **Statement review** (this page) and **Reconciliation**. The table also has a **Merchant** column.
- "Flagged only" filter, add/delete rows, view redacted raw text.
- **Smart Financial Summary**: three cards for Total Income (deposits), Total Expenses (withdrawals)
  and Savings (income minus expenses; green when positive, red when negative), plus the top expense
  category. It updates as you add, edit or delete rows, and follows the Search & Filter box.
- **Categories**: every row has a Category (Food, Shopping, Salary, Bills, Transport, Entertainment,
  Health, Education, Other), picked from the description by simple whole-word keyword matching
  (`detectCategory` in `frontend/src/utils/review.js`). Rows from the statement get their category
  when extracted and keep it when edited. A row you add follows its description until you choose a
  category yourself; your choice is never overridden. The category is saved with the statement
  (old saved statements without one show "Other").
- **Search & Filter**: description (partial, any case), From / To date, minimum / maximum amount,
  type (Income / Expense) and category. All filters work together, "Clear Filters" resets them, and
  the box shows "Showing X of Y transactions". "Add row" clears the filters so the new row is visible.
- **Save** stays disabled until all flagged items are reviewed and client validation passes;
  the backend validates again (masked account, period order, no negative amounts,
  not both deposit and withdrawal).
- **Dashboard**: combines saved statement totals by currency, shows monthly cash flow, rule-based
  anomalies, recurring debit patterns, saved merchant corrections, extraction quality, and CSV export.
  Statements in different currencies are never added together or reconciled against each other; no
  exchange-rate conversion is performed. Saved statements with overlapping dates can double-count
  transactions in dashboard totals.
- **Currency**: choose a supported ISO currency code in Statement Details. Currency symbols/codes
  found during extraction are flagged for reviewer confirmation; ambiguous symbols should be checked
  against the original document. New saves retain extraction method and confidence summary so the
  dashboard can show OCR and text-extraction quality. Existing saved statements without this metadata
  show "Not recorded".

### Merchant identification

Each narration gets a readable merchant (e.g. `UPI/P2M/98372/AMAZON` → **Amazon**, `POS/DMART/STORE01` → **DMart**),
a merchant category (Shopping, Food, Groceries, Transport, Utilities, Entertainment, Banking, Other), a confidence score
and a plain-language reason. Rules only, no AI: (1) your saved corrections, (2) a built-in dictionary of Indian brands and
a few generic services, matched as whole words after ids, dates and payment codes are removed from a *copy* of the
narration. A brand beats a generic service; two different brands in one narration, or a weak match
(confidence under 0.70), give exactly **Unknown Merchant**. Use the pencil icon in the table to correct a merchant; the
correction is saved (table `merchant_mappings`) and reused for later uploads. The original narration is never changed
and merchants are not stored inside saved statements.
Add brands in `BRANDS` / `SERVICES` at the top of `backend/statement_analyser/services/merchant_identifier.py`.

### Reconciliation (new "Reconciliation" tab)

1. **Bank accounts**: add accounts, mark the ones that are yours, link saved statements to them (optional).
2. **Choose what to compare**: *Internal* (two statements of the same account) or *Inter-bank* (two different
   accounts), plus the allowed date difference (0, 1, 2, 3, 5 or 7 days).
3. **Summary, then review**: matched, possible matches, manual review, unmatched, duplicate candidates, timing
   differences, confirmed own-account transfers, matched/unmatched amounts, CSV export.

Matching rules (`reconciliation_engine.py`): a pair always needs the same amount, a fitting direction (inter-bank: a debit
against a credit; internal: same direction) and a date inside the window. Then: **1** same reference → *Matched*;
**2** compatible description → *Matched*; **3** partly similar description or a mention of the other bank → *Possible Match*;
**4** nothing but amount and date → *Possible Match* with low confidence. If the dates differ the status is *Timing Difference*.
Equal amounts alone are never *Matched*. Several candidates with identical evidence → *Manual Review*. A transaction joins
one pair only. Same reference with a failed check (amount, direction, dates) → *Manual Review*. Duplicate candidates
(same date, amount, direction, description, no conflicting reference) are shown, never deleted. Internal reconciliation
only compares the overlapping period; transactions outside it (or outside the other statement's period in inter-bank)
are labelled *period gap*, not errors. Only matches with strong evidence are marked automatically; every uncertain one waits
for your Confirm / Reject. A transfer counts as "between my own accounts" only if both accounts are marked yours, and
only a transfer you **confirm** is left out of the combined income/expenses.
Results live in their own tables (`reconciliation_sessions`, `reconciliation_matches`) with a copy of the few fields they
show; saved statements are never modified.

### LIST branding
The interface carries the LIST logo in the header and as a faint mark in the page background; the module component keeps the mark inside its own box so it does not cover a host page.
Colours live in one place, `frontend/src/theme.js` (`BRAND`). To change the logo, replace `frontend/src/assets/list-logo-dark.png` (for light backgrounds) and `list-logo-white.png`
(for dark ones), then rebuild. The favicon is `frontend/public/favicon.png`. The logo was traced from a small screenshot, so ask for the original vector (SVG) file for a sharper result.

### Analysis (new "Analysis" tab)
Upload a statement (or pick a saved one) to get what a lender or analyst looks for: average daily and monthly balance, month-by-month money in/out, salary and how regular it is,
EMI/NACH payments (also found when the mandate number changes), bounced items, cash deposits (large ones flagged), possible circular transfers, the bank (from the IFSC code), and
file-trail warning signs (editing software, edit-on-top saves, annotations, pasted images). Everything is rule based and shows which rows caused it. Password protected PDFs work when you type the password.
Files: backend `services/analytics.py`, `tamper_check.py`, `bank_profiles.py`, `analysis.py`, `job_store.py`, `routes_analysis.py`; frontend `Analysis.jsx`, `AnalysisResult.jsx`.
Settings: `API_KEYS` (comma separated; empty = open) and `WEBHOOK_ALLOWED_HOSTS` (empty = webhooks off).

### Duplicate warnings and History (new "History" tab)
- **Before saving**, the app asks the server whether the statement looks like a **duplicate** of a saved one (same account and the same transactions, in any order),
  **overlaps** the period of a saved statement for the same account, or has **repeated rows** (same date, description and amount). You see the warnings and choose
  **Save anyway** or **Go back**. Nothing is ever blocked, and if the check fails the save still works.
- **History tab** is an audit trail: every save, every value you edited before saving (old value to new value), and every delete, newest first.
  It is kept in its own `audit_log` table; statements are not changed by it. The edit list is sent with the save request but is not stored inside the statement.
- Files: backend `services/duplicate_check.py`, `services/audit_log.py`, `routes_audit.py`; frontend `SaveWarningsDialog.jsx`, `AuditHistory.jsx`.

## 8. Optional local LLM

```bash
ollama pull llama3.1:8b
export OLLAMA_ENABLED=true OLLAMA_MODEL=llama3.1:8b
uvicorn statement_analyser.main:app --port 8000
```

If Ollama is down the API adds a warning and continues with rule-based extraction.

## 9. Configuration

| Variable | Default | Meaning |
|---|---|---|
| `MAX_UPLOAD_MB` | 10 | upload size limit |
| `MAX_PAGES` | 30 | PDF page limit |
| `MIN_TEXT_CHARS` | 60 | below this a page is OCR'd |
| `OCR_DPI` | 300 | render resolution for OCR |
| `OCR_LANG` | eng | Tesseract language |
| `REVIEW_THRESHOLD` | 0.75 | below this a field is flagged |
| `DATE_DAYFIRST` | true | `03/09/2026` = 3 Sep |
| `OLLAMA_ENABLED` | false | turn on LLM assist |
| `OLLAMA_URL` | http://localhost:11434 | |
| `OLLAMA_MODEL` | llama3.1:8b | |
| `DB_PATH` | data/statements.db | SQLite file |
| `CORS_ORIGINS` | localhost:5173 | comma separated |

The frontend needs no environment variable when using the Vite `/api` proxy. For a separately
hosted frontend, set `VITE_API_BASE_URL` to the backend URL and set `CORS_ORIGINS` on the backend
to include the frontend origin. The supplied `render.yaml` and Dockerfile deploy the combined
frontend and backend; set the variables above in the hosting provider as needed. `DB_PATH` should
point to persistent storage if saved reviews must survive container replacement. Tesseract must
be installed on the backend host for scanned PDFs and statement images; the supplied Dockerfile
installs it.

## 10. Known limitations

- Layout rules use flexible column labels and coordinates, but unusual bank formats may need
  extra header synonyms in `parser.COLUMN_KEYWORDS`.
- Handwritten text, heavy noise or photos taken at an angle reduce OCR quality; those rows get
  low scores and are flagged rather than guessed.
- Statements with separate Dr/Cr indicator columns, or balances printed only once per day,
  are only partially supported.
- No authentication — add JWT before exposing beyond localhost. Use dummy data only.
