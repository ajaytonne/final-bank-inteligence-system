"""Audit trail and duplicate-check API. Built with a factory so it shares main.py's dependencies (tests override them)."""
from typing import Optional

from fastapi import APIRouter, Depends

from statement_analyser.config import Settings
from statement_analyser.schemas import AuditEntry, ReviewedStatement, StatementWarning
from statement_analyser.services.audit_log import AuditLog, get_audit_log
from statement_analyser.services.duplicate_check import check_statement


def create_router(settings_dep, statement_store_dep) -> APIRouter:
    router = APIRouter(tags=["audit"])

    @router.post("/api/statements/check", response_model=list[StatementWarning])
    def check(body: ReviewedStatement, store=Depends(statement_store_dep)):
        """Warnings for a statement that is about to be saved. Nothing is stored."""
        saved = [(s.id, store.get(s.id).statement) for s in store.list(limit=500)]
        return check_statement(body, saved)

    @router.get("/api/audit", response_model=list[AuditEntry])
    def audit(statement_id: Optional[int] = None, s: Settings = Depends(settings_dep)):
        return get_audit_log(s.db_path).list(statement_id)

    return router
