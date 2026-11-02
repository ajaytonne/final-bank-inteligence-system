import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, Optional

from app.schemas import ReviewedStatement, SavedStatement, SavedStatementSummary

SCHEMA = """
CREATE TABLE IF NOT EXISTS statements (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    file_name TEXT NOT NULL,
    account_holder TEXT,
    transaction_count INTEGER NOT NULL,
    payload TEXT NOT NULL
)
"""


class StatementStore:
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

    def save(self, st: ReviewedStatement) -> SavedStatement:
        now = datetime.now(timezone.utc)
        with self._conn() as c:
            cur = c.execute(
                "INSERT INTO statements (created_at, file_name, account_holder, transaction_count, payload)"
                " VALUES (?, ?, ?, ?, ?)",
                (
                    now.isoformat(),
                    st.file_name,
                    st.header.account_holder,
                    len(st.transactions),
                    st.model_dump_json(),
                ),
            )
            new_id = cur.lastrowid
        return SavedStatement(id=new_id, created_at=now, statement=st)

    def list(self, limit: int = 50) -> list[SavedStatementSummary]:
        with self._conn() as c:
            rows = c.execute(
                "SELECT id, created_at, file_name, account_holder, transaction_count"
                " FROM statements ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [SavedStatementSummary(**dict(r)) for r in rows]

    def get(self, sid: int) -> Optional[SavedStatement]:
        with self._conn() as c:
            r = c.execute("SELECT id, created_at, payload FROM statements WHERE id = ?", (sid,)).fetchone()
        if r is None:
            return None
        return SavedStatement(
            id=r["id"],
            created_at=r["created_at"],
            statement=ReviewedStatement.model_validate_json(r["payload"]),
        )

    def delete(self, sid: int) -> bool:
        with self._conn() as c:
            cur = c.execute("DELETE FROM statements WHERE id = ?", (sid,))
            return cur.rowcount > 0
