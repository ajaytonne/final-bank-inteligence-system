"""One call that turns a statement file into the full analysis: extraction + bank + analytics + tamper checks + flags.

Used by the HTTP API (sync for the screens, async jobs for integrators) and by the Python module (`analyse_full`)."""
from typing import Optional

from statement_analyser.config import Settings
from statement_analyser.schemas import ReviewedStatement
from statement_analyser.services.analytics import analyse_transactions
from statement_analyser.services.bank_profiles import identify_bank
from statement_analyser.services.file_validation import ValidatedFile
from statement_analyser.services.pipeline import run_extraction
from statement_analyser.services.tamper_check import check_pdf

LEVEL_ORDER = {"high": 0, "medium": 1, "low": 2, "info": 3}


def _flags(analytics: dict, tamper: Optional[dict], extraction: Optional[dict]) -> list[dict]:
    out = []

    def add(level, code, message):
        out.append({"level": level, "code": code, "message": message})

    if tamper:
        for f in tamper["flags"]:
            add(f["severity"], f"tamper_{f['code']}", f["detail"])
    if extraction:
        if extraction["validation"]["status"] == "failed":
            add("high", "balance_chain", "The running balance does not add up. A value may have been changed or misread.")
        if extraction["review_required_count"]:
            add("medium", "needs_review", f"{extraction['review_required_count']} extracted value(s) are low confidence and need a person to check.")
    if analytics["bounces"]["count"]:
        add("medium", "bounces", f"{analytics['bounces']['count']} bounced or returned item(s).")
    if analytics["cash"]["large_deposits"]:
        add("medium", "large_cash_deposit", f"{len(analytics['cash']['large_deposits'])} cash deposit(s) of {analytics['cash']['large_deposit_threshold']} or more.")
    if analytics["circular"]["count"]:
        add("medium", "circular", f"{analytics['circular']['count']} possible circular transfer(s): same amount out and back from the same party.")
    if not analytics["salary"]["detected"]:
        add("info", "no_salary", "No salary credit was detected.")
    return sorted(out, key=lambda f: LEVEL_ORDER.get(f["level"], 9))


def analyse_file(file: ValidatedFile, settings: Settings, password: Optional[str] = None) -> dict:
    extraction = run_extraction(file, settings, password)
    header = extraction.header
    bank = identify_bank(header.ifsc.value, extraction.raw_text) or (
        {"name": header.bank_name.value, "code": None, "source": "statement"} if header.bank_name.value else None)
    analytics = analyse_transactions(extraction.transactions, header.period_start.value, header.period_end.value, header.opening_balance.value)
    tamper = check_pdf(file.data, password) if file.kind == "pdf" else {
        "status": "unavailable", "flags": [], "metadata": {}, "note": "Images have no file trail to check."}
    ext = extraction.model_dump(mode="json", exclude={"raw_text"})
    return {"file_name": file.name, "bank": bank, "extraction": ext, "analytics": analytics, "tamper": tamper,
            "flags": _flags(analytics, tamper, ext)}


def analyse_saved(statement: ReviewedStatement) -> dict:
    """Analytics on a statement a person already reviewed and saved (no file, so no tamper check)."""
    h = statement.header
    analytics = analyse_transactions(statement.transactions, h.period_start, h.period_end, h.opening_balance)
    bank = identify_bank(h.ifsc) or ({"name": h.bank_name, "code": None, "source": "statement"} if h.bank_name else None)
    return {"file_name": statement.file_name, "bank": bank, "extraction": None, "analytics": analytics, "tamper": None,
            "flags": _flags(analytics, None, None)}
