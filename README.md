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
│   ├── app/
│   │   ├── main.py           API routes
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
│   │       └── storage.py          SQLite store for reviewed statements
│   ├── scripts/sample_data.py      synthetic statement generator
│   ├── samples/                    6 ready-made dummy statements
│   └── tests/                      108 pytest tests
└── frontend/                 React 18 + Vite + MUI
    └── src/
        ├── App.jsx                  page + review state
        ├── api/client.js            fetch wrapper
        ├── utils/review.js          state mapping, validation, live balance check
        ├── components/              Upload, Summary, Header card, Transactions table, Saved list
        └── __tests__/               18 Vitest + Testing Library tests
```

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
uvicorn app.main:app --reload --port 8000
```

API docs: http://localhost:8000/docs

> `config.py` reads plain environment variables. To use `.env`, export them
> (`set -a; source .env; set +a`) or run `uvicorn app.main:app --env-file .env`.

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
cd backend  && pytest -q      # 108 passed (OCR tests auto-skip if Tesseract missing)
cd frontend && npm test       # 18 passed
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
- "Flagged only" filter, add/delete rows, view redacted raw text.
- **Save** stays disabled until all flagged items are reviewed and client validation passes;
  the backend validates again (masked account, period order, no negative amounts,
  not both deposit and withdrawal).

## 8. Optional local LLM

```bash
ollama pull llama3.1:8b
export OLLAMA_ENABLED=true OLLAMA_MODEL=llama3.1:8b
uvicorn app.main:app --port 8000
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
