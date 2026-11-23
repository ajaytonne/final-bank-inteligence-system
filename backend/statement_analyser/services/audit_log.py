"""Audit trail: a plain log of what happened to saved statements (saved, edited fields, deleted, warnings).

It only records. It never changes a statement. Entries are kept in their own table."""
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Iterator, Optional

SCHEMA = """
CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    at TEXT NOT NULL,
    statement_id INTEGER,
    action TEXT NOT NULL,
    where_text TEXT,
    field TEXT,
    old_value TEXT,
    new_value TEXT,
    detail TEXT
)
"""


class AuditLog:
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

    def record(self, action: str, statement_id: Optional[int] = None, detail: Optional[str] = None, changes=()) -> None:
        """One entry for the action, plus one entry per edited field (action "edited")."""
        now = datetime.now(timezone.utc).isoformat()
        with self._conn() as c:
            c.execute(
                "INSERT INTO audit_log (at, statement_id, action, detail) VALUES (?, ?, ?, ?)",
                (now, statement_id, action, detail),
            )
            c.executemany(
                "INSERT INTO audit_log (at, statement_id, action, where_text, field, old_value, new_value)"
                " VALUES (?, ?, 'edited', ?, ?, ?, ?)",
                [(now, statement_id, ch.where, ch.field, ch.old, ch.new) for ch in changes],
            )

    def list(self, statement_id: Optional[int] = None, limit: int = 200) -> list[dict]:
        sql = "SELECT * FROM audit_log"
        args: list = []
        if statement_id is not None:
            sql += " WHERE statement_id = ?"
            args.append(statement_id)
        sql += " ORDER BY id DESC LIMIT ?"
        args.append(limit)
        with self._conn() as c:
            rows = c.execute(sql, args).fetchall()
        return [
            {"id": r["id"], "at": r["at"], "statement_id": r["statement_id"], "action": r["action"],
             "where": r["where_text"], "field": r["field"], "old": r["old_value"], "new": r["new_value"],
             "detail": r["detail"]}
            for r in rows
        ]


@lru_cache
def get_audit_log(db_path: str) -> AuditLog:
    return AuditLog(db_path)
