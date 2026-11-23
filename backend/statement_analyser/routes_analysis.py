"""Analysis API.

  For the screens (no key needed):
    POST /api/analysis                    upload a file, get the full analysis back at once
    GET  /api/statements/{id}/analytics   analytics for a statement that was reviewed and saved
  For other systems (X-API-Key header when API_KEYS is set):
    POST   /api/v1/analyses               submit a file (+ optional password, callback_url) -> 202 with a job id
    GET    /api/v1/analyses/{id}          status, and the result when done
    GET    /api/v1/analyses               recent jobs
    DELETE /api/v1/analyses/{id}          delete a job and its result
"""
import hmac
import logging
from typing import Optional
from urllib.parse import urlparse

import httpx
import csv
import io
from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, Header, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import StreamingResponse

from statement_analyser.config import Settings
from statement_analyser.services.analysis import analyse_file, analyse_saved
from statement_analyser.services.analytics import analyse_transactions
from statement_analyser.services.file_validation import FileValidationError, validate_upload
from statement_analyser.services.job_store import JobStore, get_job_store
from statement_analyser.services.text_extraction import OCRUnavailableError

log = logging.getLogger("bank-statement-ai")


def create_router(settings_dep, statement_store_dep) -> APIRouter:
    router = APIRouter(tags=["analysis"])

    def jobs_dep(s: Settings = Depends(settings_dep)) -> JobStore:
        return get_job_store(s.db_path)

    def require_key(x_api_key: Optional[str] = Header(None), s: Settings = Depends(settings_dep)) -> None:
        if not s.api_keys:
            return  # no keys configured: open, for local use
        if not x_api_key or not any(hmac.compare_digest(x_api_key, k) for k in s.api_keys):
            raise HTTPException(401, "A valid X-API-Key header is required.", headers={"WWW-Authenticate": "ApiKey"})

    async def read_upload(file: UploadFile, s: Settings):
        data = await file.read(s.max_upload_bytes + 1)
        try:
            return validate_upload(file.filename, data, s.max_upload_bytes)
        except FileValidationError as exc:
            raise HTTPException(exc.status_code, str(exc)) from exc

    # ---- for the screens ---------------------------------------------------------------------
    @router.post("/api/analysis")
    async def analysis(file: UploadFile = File(...), password: Optional[str] = Form(None), s: Settings = Depends(settings_dep)):
        vf = await read_upload(file, s)
        try:
            return await run_in_threadpool(analyse_file, vf, s, password)
        except OCRUnavailableError as exc:
            raise HTTPException(503, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        except Exception as exc:  # noqa: BLE001
            log.exception("Analysis failed for %s", vf.name)
            raise HTTPException(500, "Analysis failed unexpectedly.") from exc

    @router.get("/api/statements/{sid}/analytics")
    def saved_analytics(sid: int, store=Depends(statement_store_dep)):
        saved = store.get(sid)
        if saved is None:
            raise HTTPException(404, "Statement not found.")
        return analyse_saved(saved.statement)

    @router.get("/api/statements/{sid}/export.csv")
    def export_csv(sid: int, store=Depends(statement_store_dep)):
        saved = store.get(sid)
        if saved is None:
            raise HTTPException(404, "Statement not found.")
        stream = io.StringIO()
        writer = csv.writer(stream)
        writer.writerow(["Date", "Effective date", "Description", "Reference", "Withdrawal", "Deposit", "Balance", "Currency", "Category"])
        for tx in saved.statement.transactions:
            writer.writerow([
                tx.date.isoformat() if tx.date else "",
                tx.effective_date.isoformat() if tx.effective_date else "",
                tx.description or "",
                tx.reference or "",
                tx.withdrawal or "",
                tx.deposit or "",
                tx.balance or "",
                saved.statement.header.currency,
                tx.category,
            ])
        stream.seek(0)
        return StreamingResponse(
            iter([stream.getvalue()]),
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="statement-{sid}.csv"'},
        )

    # ---- for other systems -------------------------------------------------------------------
    def run_job(job_id: str, vf, password: Optional[str], callback_url: Optional[str], settings: Settings, jobs: JobStore) -> None:
        jobs.set_status(job_id, "processing")
        try:
            result = analyse_file(vf, settings, password)
        except OCRUnavailableError as exc:
            jobs.finish(job_id, error=str(exc))
        except ValueError as exc:
            jobs.finish(job_id, error=str(exc))
        except Exception:  # noqa: BLE001
            log.exception("Analysis job %s failed", job_id)
            jobs.finish(job_id, error="Analysis failed unexpectedly.")
        else:
            jobs.finish(job_id, result)
        if callback_url:
            job = jobs.get(job_id)
            try:
                r = httpx.post(callback_url, json={k: job[k] for k in ("id", "status", "file_name", "error", "result")}, timeout=10, follow_redirects=False)
                jobs.set_webhook_status(job_id, f"delivered ({r.status_code})")
            except Exception as exc:  # noqa: BLE001
                jobs.set_webhook_status(job_id, f"failed ({type(exc).__name__})")

    @router.post("/api/v1/analyses", status_code=202, dependencies=[Depends(require_key)])
    async def submit(background: BackgroundTasks, file: UploadFile = File(...), password: Optional[str] = Form(None),
                     callback_url: Optional[str] = Form(None), s: Settings = Depends(settings_dep), jobs: JobStore = Depends(jobs_dep)):
        if callback_url:
            u = urlparse(callback_url)
            if u.scheme != "https" or (u.hostname or "").lower() not in s.webhook_allowed_hosts:
                raise HTTPException(422, "callback_url must be an https address on a host listed in WEBHOOK_ALLOWED_HOSTS.")
        vf = await read_upload(file, s)
        job_id = jobs.create(vf.name, callback_url)
        background.add_task(run_job, job_id, vf, password, callback_url, s, jobs)
        return {"id": job_id, "status": "queued", "status_url": f"/api/v1/analyses/{job_id}"}

    @router.get("/api/v1/analyses", dependencies=[Depends(require_key)])
    def list_jobs(jobs: JobStore = Depends(jobs_dep)):
        return jobs.list()

    @router.get("/api/v1/analyses/{job_id}", dependencies=[Depends(require_key)])
    def get_job(job_id: str, jobs: JobStore = Depends(jobs_dep)):
        job = jobs.get(job_id)
        if job is None:
            raise HTTPException(404, "Analysis not found.")
        return job

    @router.delete("/api/v1/analyses/{job_id}", status_code=204, dependencies=[Depends(require_key)])
    def delete_job(job_id: str, jobs: JobStore = Depends(jobs_dep)):
        if not jobs.delete(job_id):
            raise HTTPException(404, "Analysis not found.")

    return router
