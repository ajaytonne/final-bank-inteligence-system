import logging
from functools import lru_cache

from fastapi import Depends, FastAPI, File, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware

from app.config import Settings, get_settings
from app.schemas import (
    ExtractionResult,
    HealthResponse,
    ReviewedStatement,
    SavedStatement,
    SavedStatementSummary,
)
from app.services import llm
from app.services.file_validation import FileValidationError, validate_upload
from app.services.pipeline import run_extraction
from app.services.storage import StatementStore
from app.services.text_extraction import OCRUnavailableError, ocr_available

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("bank-statement-ai")

settings = get_settings()

app = FastAPI(
    title="Bank Statement Intelligence API",
    version="1.0.0",
    description="Extracts structured data from dummy bank statements for human review.",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["*"],
)


def settings_dep() -> Settings:
    return settings


@lru_cache
def _store(path: str) -> StatementStore:
    return StatementStore(path)


def store_dep(s: Settings = Depends(settings_dep)) -> StatementStore:
    return _store(s.db_path)


@app.get("/api/health", response_model=HealthResponse)
def health(s: Settings = Depends(settings_dep)):
    return HealthResponse(
        status="ok",
        tesseract_available=ocr_available(),
        ollama_enabled=s.ollama_enabled,
        ollama_reachable=llm.ollama_reachable(s),
    )


@app.post("/api/extract", response_model=ExtractionResult)
async def extract(file: UploadFile = File(...), s: Settings = Depends(settings_dep)):
    data = await file.read(s.max_upload_bytes + 1)
    try:
        vf = validate_upload(file.filename, data, s.max_upload_bytes)
    except FileValidationError as exc:
        raise HTTPException(exc.status_code, str(exc)) from exc
    try:
        return await run_in_threadpool(run_extraction, vf, s)
    except OCRUnavailableError as exc:
        raise HTTPException(503, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        log.exception("Extraction failed for %s", vf.name)
        raise HTTPException(500, "Extraction failed unexpectedly.") from exc


@app.post("/api/statements", response_model=SavedStatement, status_code=201)
def save_statement(body: ReviewedStatement, store: StatementStore = Depends(store_dep)):
    return store.save(body)


@app.get("/api/statements", response_model=list[SavedStatementSummary])
def list_statements(store: StatementStore = Depends(store_dep)):
    return store.list()


@app.get("/api/statements/{sid}", response_model=SavedStatement)
def get_statement(sid: int, store: StatementStore = Depends(store_dep)):
    st = store.get(sid)
    if st is None:
        raise HTTPException(404, "Statement not found.")
    return st


@app.delete("/api/statements/{sid}", status_code=204)
def delete_statement(sid: int, store: StatementStore = Depends(store_dep)):
    if not store.delete(sid):
        raise HTTPException(404, "Statement not found.")


# --- Serve the built React frontend (single-container deployment) -------------------------
# When FRONTEND_DIST points at a Vite build, the API and UI share one origin, so no CORS setup
# is needed. In local dev the directory is absent and this block does nothing.
import os  # noqa: E402
from pathlib import Path  # noqa: E402

from fastapi.responses import FileResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402

_dist = Path(os.getenv("FRONTEND_DIST", "")) if os.getenv("FRONTEND_DIST") else None
if _dist and (_dist / "index.html").is_file():
    if (_dist / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=_dist / "assets"), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa(full_path: str):
        if full_path.startswith("api/"):
            raise HTTPException(404, "Not found.")
        candidate = (_dist / full_path).resolve()
        if full_path and candidate.is_file() and _dist.resolve() in candidate.parents:
            return FileResponse(candidate)
        return FileResponse(_dist / "index.html")
