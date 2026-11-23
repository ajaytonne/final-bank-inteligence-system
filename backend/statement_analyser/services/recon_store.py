"""Storage for bank accounts and reconciliation results.

New tables only (CREATE TABLE IF NOT EXISTS): the existing `statements` table is never altered, and result rows hold
their own copy of the few transaction fields they show, so original statements are never touched.
"""
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, Optional

SCHEMA = [
    """CREATE TABLE IF NOT EXISTS bank_accounts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        bank_name TEXT NOT NULL,
        account_label TEXT NOT NULL,
        account_number_masked TEXT,
        ownership_confirmed INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS statement_accounts (
        statement_id INTEGER PRIMARY KEY,
        account_id INTEGER NOT NULL REFERENCES bank_accounts(id) ON DELETE CASCADE,
        assigned_at TEXT NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS reconciliation_sessions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        kind TEXT NOT NULL CHECK (kind IN ('internal', 'inter_bank')),
        statement_a_id INTEGER NOT NULL,
        statement_b_id INTEGER NOT NULL,
        a_label TEXT NOT NULL,
        b_label TEXT NOT NULL,
        date_window_days INTEGER NOT NULL,
        status TEXT NOT NULL CHECK (status IN ('created', 'completed')),
        total_a INTEGER NOT NULL DEFAULT 0,
        total_b INTEGER NOT NULL DEFAULT 0,
        notes TEXT NOT NULL DEFAULT '[]',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS reconciliation_matches (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id INTEGER NOT NULL REFERENCES reconciliation_sessions(id) ON DELETE CASCADE,
        a_statement_id INTEGER, a_index INTEGER,
        b_statement_id INTEGER, b_index INTEGER,
        match_type TEXT NOT NULL,
        status TEXT NOT NULL,
        reason TEXT NOT NULL,
        confidence REAL NOT NULL,
        confirmation_status TEXT NOT NULL CHECK (confirmation_status IN ('auto', 'pending', 'confirmed', 'rejected', 'none')),
        internal_transfer INTEGER NOT NULL DEFAULT 0,
        a_reference TEXT, b_reference TEXT,
        a_snapshot TEXT, b_snapshot TEXT,
        note TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL)""",
    "CREATE INDEX IF NOT EXISTS idx_recon_matches_session ON reconciliation_matches(session_id)",
]
ACTIVE = ("Matched", "Timing Difference")  # a pair that holds its two transactions


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _match(r: sqlite3.Row) -> dict:
    d = dict(r)
    for k in ("a_snapshot", "b_snapshot"):
        d[k] = json.loads(d[k]) if d[k] else None
    d["internal_transfer"] = bool(d["internal_transfer"])
    return d


class ReconStore:
    def __init__(self, db_path: str):
        self.db_path = db_path
        if db_path != ":memory:":
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as c:
            for stmt in SCHEMA:
                c.execute(stmt)

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    # ---- bank accounts ----
    def create_account(self, bank_name: str, account_label: str, masked: Optional[str], owned: bool) -> dict:
        now = _now()
        with self._conn() as c:
            cur = c.execute(
                "INSERT INTO bank_accounts (bank_name, account_label, account_number_masked, ownership_confirmed, created_at, updated_at)"
                " VALUES (?, ?, ?, ?, ?, ?)", (bank_name, account_label, masked, int(owned), now, now))
            return self._account(c, cur.lastrowid)

    @staticmethod
    def _account(c, account_id: int) -> Optional[dict]:
        r = c.execute("SELECT * FROM bank_accounts WHERE id = ?", (account_id,)).fetchone()
        if r is None:
            return None
        d = dict(r)
        d["ownership_confirmed"] = bool(d["ownership_confirmed"])
        return d

    def get_account(self, account_id: int) -> Optional[dict]:
        with self._conn() as c:
            return self._account(c, account_id)

    def list_accounts(self) -> list[dict]:
        with self._conn() as c:
            ids = [r["id"] for r in c.execute("SELECT id FROM bank_accounts ORDER BY id")]
            return [self._account(c, i) for i in ids]

    def update_account(self, account_id: int, changes: dict) -> Optional[dict]:
        allowed = {"bank_name", "account_label", "account_number_masked", "ownership_confirmed"}
        sets = {k: (int(v) if k == "ownership_confirmed" else v) for k, v in changes.items() if k in allowed}
        with self._conn() as c:
            if self._account(c, account_id) is None:
                return None
            if sets:
                cols = ", ".join(f"{k} = ?" for k in sets)
                c.execute(f"UPDATE bank_accounts SET {cols}, updated_at = ? WHERE id = ?", (*sets.values(), _now(), account_id))
            return self._account(c, account_id)

    def assign_statement(self, statement_id: int, account_id: Optional[int]) -> None:
        with self._conn() as c:
            if account_id is None:
                c.execute("DELETE FROM statement_accounts WHERE statement_id = ?", (statement_id,))
            else:
                c.execute("INSERT INTO statement_accounts (statement_id, account_id, assigned_at) VALUES (?, ?, ?)"
                          " ON CONFLICT(statement_id) DO UPDATE SET account_id = excluded.account_id, assigned_at = excluded.assigned_at",
                          (statement_id, account_id, _now()))

    def assignments(self) -> list[dict]:
        with self._conn() as c:
            return [dict(r) for r in c.execute("SELECT statement_id, account_id FROM statement_accounts ORDER BY statement_id")]

    def account_for_statement(self, statement_id: int) -> Optional[dict]:
        with self._conn() as c:
            r = c.execute("SELECT account_id FROM statement_accounts WHERE statement_id = ?", (statement_id,)).fetchone()
            return self._account(c, r["account_id"]) if r else None

    # ---- sessions ----
    @staticmethod
    def _session(r: sqlite3.Row) -> dict:
        d = dict(r)
        d["notes"] = json.loads(d["notes"])
        return d

    def create_session(self, kind: str, a_id: int, b_id: int, a_label: str, b_label: str, window: int) -> dict:
        now = _now()
        with self._conn() as c:
            cur = c.execute(
                "INSERT INTO reconciliation_sessions (kind, statement_a_id, statement_b_id, a_label, b_label, date_window_days, status, created_at, updated_at)"
                " VALUES (?, ?, ?, ?, ?, ?, 'created', ?, ?)", (kind, a_id, b_id, a_label, b_label, window, now, now))
            return self._session(c.execute("SELECT * FROM reconciliation_sessions WHERE id = ?", (cur.lastrowid,)).fetchone())

    def get_session(self, session_id: int) -> Optional[dict]:
        with self._conn() as c:
            r = c.execute("SELECT * FROM reconciliation_sessions WHERE id = ?", (session_id,)).fetchone()
        return self._session(r) if r else None

    def list_sessions(self) -> list[dict]:
        with self._conn() as c:
            return [self._session(r) for r in c.execute("SELECT * FROM reconciliation_sessions ORDER BY id DESC LIMIT 100")]

    def delete_session(self, session_id: int) -> bool:
        with self._conn() as c:  # results go with it (ON DELETE CASCADE); statements are not touched
            return c.execute("DELETE FROM reconciliation_sessions WHERE id = ?", (session_id,)).rowcount > 0

    def save_results(self, session_id: int, rows: list, total_a: int, total_b: int, notes: list) -> None:
        now = _now()
        with self._conn() as c:
            c.executemany(
                "INSERT INTO reconciliation_matches (session_id, a_statement_id, a_index, b_statement_id, b_index, match_type, status, reason,"
                " confidence, confirmation_status, internal_transfer, a_reference, b_reference, a_snapshot, b_snapshot, created_at, updated_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [self._values(session_id, r, now) for r in rows])
            c.execute("UPDATE reconciliation_sessions SET status = 'completed', total_a = ?, total_b = ?, notes = ?, updated_at = ? WHERE id = ?",
                      (total_a, total_b, json.dumps(notes), now, session_id))

    @staticmethod
    def _values(session_id: int, r: dict, now: str) -> tuple:
        return (session_id, r["a_statement_id"], r["a_index"], r["b_statement_id"], r["b_index"], r["match_type"], r["status"], r["reason"],
                r["confidence"], r["confirmation_status"], r["internal_transfer"], r["a_reference"], r["b_reference"],
                json.dumps(r["a_snapshot"]) if r["a_snapshot"] else None, json.dumps(r["b_snapshot"]) if r["b_snapshot"] else None, now, now)

    # ---- results ----
    def matches(self, session_id: int) -> list[dict]:
        with self._conn() as c:
            return [_match(r) for r in c.execute("SELECT * FROM reconciliation_matches WHERE session_id = ? ORDER BY id", (session_id,))]

    def get_match(self, session_id: int, match_id: int) -> Optional[dict]:
        with self._conn() as c:
            r = c.execute("SELECT * FROM reconciliation_matches WHERE id = ? AND session_id = ?", (match_id, session_id)).fetchone()
        return _match(r) if r else None

    def set_decision(self, match_id: int, status: str, confirmation: str, note: Optional[str]) -> dict:
        with self._conn() as c:
            c.execute("UPDATE reconciliation_matches SET status = ?, confirmation_status = ?, note = ?, updated_at = ? WHERE id = ?",
                      (status, confirmation, note, _now(), match_id))
            return _match(c.execute("SELECT * FROM reconciliation_matches WHERE id = ?", (match_id,)).fetchone())

    def add_unmatched(self, session_id: int, row: dict) -> None:
        with self._conn() as c:
            c.execute(
                "INSERT INTO reconciliation_matches (session_id, a_statement_id, a_index, b_statement_id, b_index, match_type, status, reason,"
                " confidence, confirmation_status, internal_transfer, a_reference, b_reference, a_snapshot, b_snapshot, created_at, updated_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", self._values(session_id, row, _now()))

    def holders(self, session_id: int, statement_id: int, index: int, exclude_match_id: int) -> list[dict]:
        """Other pairs in this session that already hold this transaction (Matched / Timing Difference, auto or confirmed)."""
        marks = ",".join("?" * len(ACTIVE))
        with self._conn() as c:
            rows = c.execute(
                f"SELECT * FROM reconciliation_matches WHERE session_id = ? AND id != ? AND status IN ({marks})"
                " AND confirmation_status IN ('auto', 'confirmed')"
                " AND ((a_statement_id = ? AND a_index = ?) OR (b_statement_id = ? AND b_index = ?))",
                (session_id, exclude_match_id, *ACTIVE, statement_id, index, statement_id, index)).fetchall()
        return [_match(r) for r in rows]

    def still_in_play(self, session_id: int, statement_id: int, index: int, exclude_match_id: int) -> bool:
        """True when some other, not rejected, result row still refers to this transaction."""
        with self._conn() as c:
            return c.execute(
                "SELECT 1 FROM reconciliation_matches WHERE session_id = ? AND id != ? AND status != 'Rejected Match'"
                " AND ((a_statement_id = ? AND a_index = ?) OR (b_statement_id = ? AND b_index = ?)) LIMIT 1",
                (session_id, exclude_match_id, statement_id, index, statement_id, index)).fetchone() is not None
