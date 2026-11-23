# Statement Analyser as a module

The project can be used inside another application in two ways. The standalone app (README) works exactly as before.

| You want | Use |
|---|---|
| Read a statement from your own Python code | `analyse(...)`, or `analyse_full(...)` for the complete analysis |
| The whole API inside your FastAPI app | `mount(...)` |
| The screens inside your React app | `<StatementAnalyser />` |
| It running on its own, called over HTTP | the Dockerfile (unchanged) |

## 1. Backend (Python 3.10+, FastAPI)

The package is `statement_analyser` (it was `app`, renamed so it cannot clash with the host's own `app` package).

```bash
cd backend
pip install -e .            # or: pip install -e ".[ocr,server]"  for OCR engines and uvicorn
```

**Read one statement**
```python
from statement_analyser import analyse

result = analyse("march.pdf")                        # a path ...
result = analyse(file_bytes, name="march.pdf")       # ... or bytes plus a file name
result.header.account_holder.value
for t in result.transactions:
    t.description.value, t.withdrawal.value, t.confidence, t.needs_review
```
Nothing is saved; saving is the host's decision. It raises `FileValidationError` for unsupported or unsafe files,
`OCRUnavailableError` for a scan without an OCR engine, and `ValueError` when nothing is readable.

**Add the whole API to a FastAPI app**
```python
from fastapi import FastAPI
from statement_analyser import mount

host = FastAPI()
mount(host, prefix="/statement-analyser", db_path="/data/statement_analyser.db")
```
The API is then at `/statement-analyser/api/...` (statements, merchants, reconciliation, audit, health) and its docs at
`/statement-analyser/docs`. The host's own routes are untouched. A runnable example is in `examples/host_app.py`.
Settings (`MAX_UPLOAD_MB`, `OCR_LANG`, `OLLAMA_ENABLED` ...) are environment variables, listed in the README. They are read once, when the
module is first loaded; `db_path` must therefore be given on the first call.

Not on FastAPI (Django, Express, Spring ...)? Run it as its own service (Dockerfile) and call its HTTP API from the host.

## 2. Frontend (React 18 + MUI 6)

```bash
cd frontend
npm run build:module        # -> dist-module/statement-analyser.js  (React, MUI and emotion are not bundled)
```
```jsx
import StatementAnalyser from "./statement-analyser.js";
<StatementAnalyser apiBase="/statement-analyser" title="Statement Analyser" />
```
`apiBase` is where the host's backend mounted the module; keep it on the same origin as the page so no CORS setup is needed.
`theme` (optional) takes your MUI theme. Example: `examples/host_page.jsx`.

## 3. Full analysis (what lenders and analysts expect)

```python
from statement_analyser import analyse_full
out = analyse_full("march.pdf", password=None)     # JSON-ready dict
out["bank"], out["analytics"], out["tamper"], out["flags"]
```
- `analytics`: average/min/max daily balance, monthly view, salary and regularity, EMI/NACH obligations and their share of salary, bounces, cash deposits (large flagged), circular transfers, largest movements.
- `tamper`: file-trail warning signs (editing tool, edit-on-top saves, annotations, pasted images). `flags`: everything worth a person's attention, most serious first.
- Money is returned as strings with two decimals. Every detected item lists the rows that caused it.

**HTTP API for other systems** (asynchronous, like the market tools):
```
POST   /api/v1/analyses          file (+ password, callback_url)  ->  202 {"id": ..., "status": "queued"}
GET    /api/v1/analyses/{id}     {"status": "queued|processing|done|failed", "result": {...}, "error": ...}
GET    /api/v1/analyses          recent jobs            DELETE /api/v1/analyses/{id}
```
Set `API_KEYS=key1,key2` to require an `X-API-Key` header on these. Set `WEBHOOK_ALLOWED_HOSTS=hooks.example.com` to allow a `callback_url` (https only, listed hosts only);
the finished job is then POSTed there. Jobs run inside the server process (fine for light use; for volume move them to a worker queue).

## 4. What the host still has to decide (not built yet)

- **Login and per-user data.** The module has no users. Everything saved is visible to anyone who can reach it. Until it has user
  accounts, protect the prefix in the host (middleware or the gateway).
  Next step: a `user_id` on every table and a hook that tells the module who is calling.
- **Database.** SQLite file today (`db_path`). For several servers, move to the host's database (Postgres).
- **Sensitive data.** Bank statements: encryption at rest, retention and access logs should follow the host's rules.
  Use dummy statements until then.
- **OCR for scans** needs Tesseract on the server (or `pip install -e ".[ocr]"` for the pip-only engine).
