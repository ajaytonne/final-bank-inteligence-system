from decimal import Decimal
from typing import Optional

from app.schemas import BalanceValidation
from app.services.parser import FieldGuess, ParsedStatement, RawRow

TOL = Decimal("0.01")
PASS_BOOST = 0.04
FAIL_FACTOR = 0.6


def _close(a: Decimal, b: Decimal) -> bool:
    return abs(a - b) <= TOL


def _val(f: FieldGuess) -> Decimal:
    return f.value if f.value is not None else Decimal("0")


def _boost(f: FieldGuess):
    if f.value is not None:
        f.confidence = round(min(f.confidence + PASS_BOOST, 0.99), 3)


def _penalise(f: FieldGuess):
    if f.value is not None:
        f.confidence = round(f.confidence * FAIL_FACTOR, 3)


def _resolve_side(row: RawRow, prev: Optional[Decimal]):
    amt = row.unassigned
    if amt is None:
        return
    bal = row.balance.value
    base = row.balance.confidence
    if prev is not None and bal is not None:
        if _close(prev - amt, bal):
            row.withdrawal = FieldGuess(amt, base, row.source, "Side inferred from balance", False)
        elif _close(prev + amt, bal):
            row.deposit = FieldGuess(amt, base, row.source, "Side inferred from balance", False)
    if row.deposit.value is None and row.withdrawal.value is None:
        target = "deposit" if row.side_hint == "cr" else "withdrawal"
        note = (
            "Side taken from Cr/Dr marker" if row.side_hint
            else "Side could not be confirmed; please verify"
        )
        setattr(row, target, FieldGuess(amt, round(base * 0.5, 3), row.source, note, False))
        row.issues.append("Deposit/withdrawal side uncertain")
    row.unassigned = None


def validate_balances(parsed: ParsedStatement) -> BalanceValidation:
    h = parsed.header
    rows = parsed.rows
    opening = h["opening_balance"].value
    stated_closing = h["closing_balance"].value

    if opening is None and rows and rows[0].balance.value is not None:
        r0 = rows[0]
        if r0.unassigned is None:
            derived = r0.balance.value - _val(r0.deposit) + _val(r0.withdrawal)
            h["opening_balance"] = FieldGuess(
                derived, 0.6, "derived", "Derived from first transaction; verify"
            )
            opening = derived

    if not rows:
        return BalanceValidation(
            status="unavailable",
            stated_closing=stated_closing,
            note="No transaction rows were found.",
        )

    prev = opening
    mismatched: list[int] = []
    checked = 0
    for row in rows:
        _resolve_side(row, prev)
        dep, wd, bal = _val(row.deposit), _val(row.withdrawal), row.balance.value
        if prev is not None and bal is not None:
            checked += 1
            if _close(prev + dep - wd, bal):
                for f in (row.deposit, row.withdrawal, row.balance):
                    _boost(f)
            elif (dep or wd) and _close(prev - dep + wd, bal):
                row.deposit, row.withdrawal = row.withdrawal, row.deposit
                for f in (row.deposit, row.withdrawal):
                    if f.value is not None:
                        f.confidence = round(f.confidence * 0.75, 3)
                        f.note = "Column swapped to match running balance"
                row.issues.append("Deposit/withdrawal swapped to match running balance")
            else:
                mismatched.append(row.index)
                row.issues.append(
                    f"Running balance mismatch: expected {prev + dep - wd}, found {bal}"
                )
                for f in (row.deposit, row.withdrawal, row.balance):
                    _penalise(f)
        if bal is not None:
            prev = bal
        elif prev is not None:
            prev = prev + dep - wd

    computed = prev
    if checked == 0:
        return BalanceValidation(
            status="unavailable",
            computed_closing=computed,
            stated_closing=stated_closing,
            note="Not enough balance data to verify the running balance.",
        )

    closing_ok = True
    note = None
    if stated_closing is not None and computed is not None:
        closing_ok = _close(computed, stated_closing)
        if not closing_ok:
            note = f"Computed closing {computed} differs from stated closing {stated_closing}."
            _penalise(h["closing_balance"])
    elif stated_closing is None:
        note = "Closing balance not stated; only row balances were checked."

    status = "passed" if not mismatched and closing_ok else "failed"
    return BalanceValidation(
        status=status,
        computed_closing=computed,
        stated_closing=stated_closing,
        mismatched_rows=mismatched,
        note=note,
    )
