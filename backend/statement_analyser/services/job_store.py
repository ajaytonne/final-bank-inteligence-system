"""Stores analysis jobs for the asynchronous API (submit a file, check back for the result)."""
import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Iterator, Optional

SCHEMA = """
CREATE TABLE IF NOT EXISTS analysis_jobs (
    id TEXT PRIMARY KEY,
    status TEXT NOT NULL,
    file_name TEXT NOT NULL,
    created_at TEXT NOT NULL,
    finished_at TEXT,
    result TEXT,
    error TEXT,
    callback_url TEXT,
    webhook_status TEXT
)
"""
STATUSES = ("queued", "processing", "done", "failed")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class JobStore:
    def __init__(self, db_path: str):
        self.db_path = db_path
        if db_path != ":memory:":
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as c:
            c.execute(SCHEMA)

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def create(self, file_name: str, callback_url: Optional[str] = None) -> str:
        job_id = uuid.uuid4().hex
        with self._conn() as c:
            c.execute("INSERT INTO analysis_jobs (id, status, file_name, created_at, callback_url) VALUES (?, 'queued', ?, ?, ?)",
                      (job_id, file_name, _now(), callback_url))
        return job_id

    def set_status(self, job_id: str, status: str) -> None:
        with self._conn() as c:
            c.execute("UPDATE analysis_jobs SET status = ? WHERE id = ?", (status, job_id))

    def finish(self, job_id: str, result: Optional[dict] = None, error: Optional[str] = None) -> None:
        with self._conn() as c:
            c.execute("UPDATE analysis_jobs SET status = ?, finished_at = ?, result = ?, error = ? WHERE id = ?",
                      ("failed" if error else "done", _now(), json.dumps(result) if result is not None else None, error, job_id))

    def set_webhook_status(self, job_id: str, text: str) -> None:
        with self._conn() as c:
            c.execute("UPDATE analysis_jobs SET webhook_status = ? WHERE id = ?", (text, job_id))

    @staticmethod
    def _row(r, with_result: bool) -> dict:
        d = {"id": r["id"], "status": r["status"], "file_name": r["file_name"], "created_at": r["created_at"],
             "finished_at": r["finished_at"], "error": r["error"], "webhook_status": r["webhook_status"]}
        if with_result:
            d["result"] = json.loads(r["result"]) if r["result"] else None
        return d

    def get(self, job_id: str) -> Optional[dict]:
        with self._conn() as c:
            r = c.execute("SELECT * FROM analysis_jobs WHERE id = ?", (job_id,)).fetchone()
        return self._row(r, True) if r else None

    def list(self, limit: int = 50) -> list[dict]:
        with self._conn() as c:
            rows = c.execute("SELECT * FROM analysis_jobs ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
        return [self._row(r, False) for r in rows]

    def delete(self, job_id: str) -> bool:
        with self._conn() as c:
            return c.execute("DELETE FROM analysis_jobs WHERE id = ?", (job_id,)).rowcount > 0


@lru_cache
def get_job_store(db_path: str) -> JobStore:
    return JobStore(db_path)
