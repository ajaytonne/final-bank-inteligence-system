"""Duplicate and overlap checks for a statement about to be saved. Pure functions: no database, no changes.

Only warnings. The person decides whether to save anyway."""
import datetime as dt
import re
from collections import Counter
from typing import Optional

from statement_analyser.schemas import ReviewedStatement, StatementWarning


def _last4(st: ReviewedStatement) -> str:
    digits = re.findall(r"\d", st.header.account_number_masked or "")
    return "".join(digits[-4:])


def _row_key(t) -> tuple:
    desc = re.sub(r"\s+", " ", (t.description or "").strip().lower())
    return (t.date, desc, t.deposit or 0, t.withdrawal or 0)


def fingerprint(st: ReviewedStatement) -> tuple:
    """The same transactions in any order give the same fingerprint."""
    return tuple(sorted(Counter(_row_key(t) for t in st.transactions).items(), key=repr))


def _same_account(a: ReviewedStatement, b: ReviewedStatement) -> bool:
    la, lb = _last4(a), _last4(b)
    if not la or not lb or la != lb:
        return False
    ba, bb = (a.header.bank_name or "").lower(), (b.header.bank_name or "").lower()
    return not (ba and bb and ba != bb)


def _overlap_days(a: ReviewedStatement, b: ReviewedStatement) -> int:
    s1, e1, s2, e2 = a.header.period_start, a.header.period_end, b.header.period_start, b.header.period_end
    if not (s1 and e1 and s2 and e2):
        return 0
    return max(0, (min(e1, e2) - max(s1, s2)).days + 1)


def check_statement(new: ReviewedStatement, saved: list[tuple[int, ReviewedStatement]]) -> list[StatementWarning]:
    warnings: list[StatementWarning] = []
    new_print = fingerprint(new) if new.transactions else None
    for sid, old in saved:
        if new_print is not None and fingerprint(old) == new_print and _same_account(new, old):
            warnings.append(StatementWarning(
                kind="duplicate", statement_id=sid,
                message=f"Looks like a duplicate of saved statement #{sid} ({old.file_name}): same account and the same transactions."))
        elif _same_account(new, old) and _overlap_days(new, old):
            days = _overlap_days(new, old)
            warnings.append(StatementWarning(
                kind="overlap", statement_id=sid,
                message=f"The period overlaps saved statement #{sid} ({old.file_name}) for the same account by {days} day(s)."))
    repeated = [k for k, n in Counter(_row_key(t) for t in new.transactions if t.date).items() if n > 1 and (k[2] or k[3])]
    if repeated:
        warnings.append(StatementWarning(
            kind="repeated_rows",
            message=f"{len(repeated)} transaction(s) appear more than once with the same date, description and amount. "
                    "That can be normal, but check it is not a double entry."))
    return warnings
