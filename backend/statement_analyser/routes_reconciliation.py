"""Bank accounts and reconciliation API. Built with a factory so it shares main.py's dependencies (tests override them)."""
import csv
import io
from functools import lru_cache

from fastapi import APIRouter, Depends, HTTPException, Response

from statement_analyser.config import Settings
from statement_analyser.schemas import (
    AssignAccount, BankAccount, BankAccountIn, BankAccountUpdate, Consolidated, ReconCreate, ReconDecision,
    ReconDetail, ReconSession, StatementAccount,
)
from statement_analyser.services.recon_store import ReconStore
from statement_analyser.services.reconciliation_engine import (
    DUPLICATE, INTERNAL, MATCHED, MISSING, PAIR_STATUSES, REJECTED, UNMATCHED, build_side, build_summary,
    check_accounts, consolidate, reconcile,
)


@lru_cache
def _store(path: str) -> ReconStore:
    return ReconStore(path)


def create_router(settings_dep, statement_store_dep) -> APIRouter:
    router = APIRouter(tags=["reconciliation"])

    def recon_dep(s: Settings = Depends(settings_dep)) -> ReconStore:
        return _store(s.db_path)

    def load_side(statements, recon: ReconStore, statement_id: int):
        saved = statements.get(statement_id)
        if saved is None:
            raise HTTPException(404, f"Statement {statement_id} not found. It may have been deleted.")
        return build_side(statement_id, saved.statement, recon.account_for_statement(statement_id))

    def get_session(recon: ReconStore, session_id: int) -> dict:
        session = recon.get_session(session_id)
        if session is None:
            raise HTTPException(404, "Reconciliation not found.")
        return session

    def detail(recon: ReconStore, session_id: int) -> dict:
        session = get_session(recon, session_id)
        rows = recon.matches(session_id)
        return {
            "session": session,
            "summary": build_summary(rows, session["total_a"], session["total_b"]),
            "matches": [{**r, "a": r["a_snapshot"], "b": r["b_snapshot"]} for r in rows],
        }

    # ---- bank accounts ----
    @router.get("/api/bank-accounts", response_model=list[BankAccount])
    def list_accounts(recon: ReconStore = Depends(recon_dep)):
        return recon.list_accounts()

    @router.post("/api/bank-accounts", response_model=BankAccount, status_code=201)
    def create_account(body: BankAccountIn, recon: ReconStore = Depends(recon_dep)):
        return recon.create_account(body.bank_name.strip(), body.account_label.strip(), body.account_number_masked, body.ownership_confirmed)

    @router.put("/api/bank-accounts/{account_id}", response_model=BankAccount)
    def update_account(account_id: int, body: BankAccountUpdate, recon: ReconStore = Depends(recon_dep)):
        account = recon.update_account(account_id, body.model_dump(exclude_unset=True))
        if account is None:
            raise HTTPException(404, "Bank account not found.")
        return account

    @router.get("/api/statement-accounts", response_model=list[StatementAccount])
    def list_assignments(recon: ReconStore = Depends(recon_dep)):
        return recon.assignments()

    @router.put("/api/statements/{statement_id}/account", response_model=StatementAccount)
    def assign_account(statement_id: int, body: AssignAccount, statements=Depends(statement_store_dep), recon: ReconStore = Depends(recon_dep)):
        if statements.get(statement_id) is None:
            raise HTTPException(404, "Statement not found.")
        if body.account_id is not None and recon.get_account(body.account_id) is None:
            raise HTTPException(404, "Bank account not found.")
        recon.assign_statement(statement_id, body.account_id)
        return {"statement_id": statement_id, "account_id": body.account_id}

    # ---- sessions ----
    @router.post("/api/reconciliations", response_model=ReconSession, status_code=201)
    def create_session(body: ReconCreate, statements=Depends(statement_store_dep), recon: ReconStore = Depends(recon_dep)):
        if body.statement_a_id == body.statement_b_id:
            raise HTTPException(422, "Choose two different statements.")
        a, b = load_side(statements, recon, body.statement_a_id), load_side(statements, recon, body.statement_b_id)
        error = check_accounts(body.kind, a, b)
        if error:
            raise HTTPException(422, error)
        window = body.date_window_days if body.date_window_days is not None else (0 if body.kind == INTERNAL else 2)
        return recon.create_session(body.kind, a.statement_id, b.statement_id, a.label, b.label, window)

    @router.post("/api/reconciliations/{session_id}/run", response_model=ReconDetail)
    def run_session(session_id: int, statements=Depends(statement_store_dep), recon: ReconStore = Depends(recon_dep)):
        session = get_session(recon, session_id)
        if session["status"] != "created":
            raise HTTPException(409, "This reconciliation has already been run. Create a new one to run it again.")
        a, b = load_side(statements, recon, session["statement_a_id"]), load_side(statements, recon, session["statement_b_id"])
        error = check_accounts(session["kind"], a, b)
        if error:
            raise HTTPException(422, error)
        out = reconcile(a, b, session["kind"], session["date_window_days"])
        recon.save_results(session_id, out["rows"], out["total_a"], out["total_b"], out["notes"])
        return detail(recon, session_id)

    @router.get("/api/reconciliations", response_model=list[ReconSession])
    def list_sessions(recon: ReconStore = Depends(recon_dep)):
        return recon.list_sessions()

    @router.get("/api/reconciliations/{session_id}", response_model=ReconDetail)
    def get_detail(session_id: int, recon: ReconStore = Depends(recon_dep)):
        return detail(recon, session_id)

    @router.delete("/api/reconciliations/{session_id}", status_code=204)
    def delete_session(session_id: int, recon: ReconStore = Depends(recon_dep)):
        if not recon.delete_session(session_id):
            raise HTTPException(404, "Reconciliation not found.")

    # ---- manual decisions ----
    def pair_or_error(recon: ReconStore, session_id: int, match_id: int) -> dict:
        get_session(recon, session_id)
        m = recon.get_match(session_id, match_id)
        if m is None:
            raise HTTPException(404, "Match not found.")
        if m["a_index"] is None or m["b_index"] is None:
            raise HTTPException(422, "Only a pair of transactions can be confirmed or rejected.")
        return m

    @router.post("/api/reconciliations/{session_id}/matches/{match_id}/confirm", response_model=ReconDetail)
    def confirm(session_id: int, match_id: int, body: ReconDecision = ReconDecision(), recon: ReconStore = Depends(recon_dep)):
        m = pair_or_error(recon, session_id, match_id)
        if m["status"] == DUPLICATE:
            recon.set_decision(match_id, DUPLICATE, "confirmed", body.note)  # a confirmed duplicate stays visible; nothing is deleted
        else:
            for stmt_id, index in ((m["a_statement_id"], m["a_index"]), (m["b_statement_id"], m["b_index"])):
                other = recon.holders(session_id, stmt_id, index, match_id)
                if other:
                    raise HTTPException(409, f"Transaction {index + 1} of statement {stmt_id} already belongs to another matched pair "
                                             f"(#{other[0]['id']}). Reject that pair first.")
            recon.set_decision(match_id, m["status"] if m["status"] in PAIR_STATUSES else MATCHED, "confirmed", body.note)
        return detail(recon, session_id)

    @router.post("/api/reconciliations/{session_id}/matches/{match_id}/reject", response_model=ReconDetail)
    def reject(session_id: int, match_id: int, body: ReconDecision = ReconDecision(), recon: ReconStore = Depends(recon_dep)):
        m = pair_or_error(recon, session_id, match_id)
        recon.set_decision(match_id, REJECTED, "rejected", body.note)
        # A transaction left with no other result row would disappear: report it as unmatched instead.
        for side in ("a", "b"):
            stmt_id, index = m[f"{side}_statement_id"], m[f"{side}_index"]
            if recon.still_in_play(session_id, stmt_id, index, match_id):
                continue
            row = {"a_statement_id": None, "a_index": None, "b_statement_id": None, "b_index": None, "a_reference": "", "b_reference": "",
                   "a_snapshot": None, "b_snapshot": None, "match_type": "Rejected", "status": UNMATCHED, "confidence": 1.0,
                   "confirmation_status": "none", "internal_transfer": 0,
                   "reason": "The match was rejected, so this transaction is unmatched."}
            row.update({f"{side}_statement_id": stmt_id, f"{side}_index": index, f"{side}_reference": m[f"{side}_reference"],
                        f"{side}_snapshot": m[f"{side}_snapshot"]})
            recon.add_unmatched(session_id, row)
        return detail(recon, session_id)

    # ---- totals and export ----
    @router.get("/api/reconciliations/{session_id}/consolidated", response_model=Consolidated)
    def consolidated(session_id: int, statements=Depends(statement_store_dep), recon: ReconStore = Depends(recon_dep)):
        session = get_session(recon, session_id)
        sides = [load_side(statements, recon, session["statement_a_id"]), load_side(statements, recon, session["statement_b_id"])]
        return consolidate(sides, recon.matches(session_id))

    @router.get("/api/reconciliations/{session_id}/export")
    def export(session_id: int, recon: ReconStore = Depends(recon_dep)):
        data = detail(recon, session_id)
        session = data["session"]
        buf = io.StringIO()
        out = csv.writer(buf)
        out.writerow(["Status", "Match type", "Confidence", "Confirmation", "Possible internal transfer", "Reason",
                      "A statement", "A row", "A date", "A description", "A reference", "A direction", "A amount",
                      "B statement", "B row", "B date", "B description", "B reference", "B direction", "B amount", "Note"])
        for m in data["matches"]:
            cells = [m["status"], m["match_type"], m["confidence"], m["confirmation_status"], "yes" if m["internal_transfer"] else "no", m["reason"]]
            for side, label in (("a", session["a_label"]), ("b", session["b_label"])):
                snap = m[side]
                cells += [label if snap else "", (m[f"{side}_index"] + 1) if snap else "", *(
                    [snap["date"], snap["description"], snap["reference"], snap["direction"], snap["amount"]] if snap else [""] * 5)]
            cells.append(m["note"] or "")
            out.writerow([_safe(c) for c in cells])
        return Response(
            content=("﻿" + buf.getvalue()).encode("utf-8"),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="reconciliation-{session_id}.csv"'},
        )

    return router


def _safe(value) -> str:
    """Stop spreadsheet programs from running a cell as a formula."""
    text = "" if value is None else str(value)
    return "'" + text if text[:1] in ("=", "+", "-", "@", "\t", "\r") else text
