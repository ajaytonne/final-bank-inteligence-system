from decimal import Decimal

from app.services.parser import FieldGuess, ParsedStatement, RawRow
from app.services.validation import validate_balances

D = Decimal


def fg(v, conf=0.9, required=True):
    return FieldGuess(D(v) if v is not None else None, conf if v is not None else 0.0, "pdf_text" if v is not None else "none", None, required)


def row(i, dep=None, wd=None, bal=None, unassigned=None, hint=None):
    return RawRow(
        index=i, page=1, source="pdf_text",
        date=FieldGuess("2026-09-01", 0.9, "pdf_text"),
        description=FieldGuess("x", 0.9, "pdf_text"),
        reference=FieldGuess(required=False),
        deposit=fg(dep, required=False), withdrawal=fg(wd, required=False), balance=fg(bal),
        unassigned=D(unassigned) if unassigned else None, side_hint=hint,
    )


def header(opening=None, closing=None):
    keys = ["account_holder", "account_number_masked", "period_start", "period_end"]
    h = {k: FieldGuess() for k in keys}
    h["opening_balance"] = fg(opening)
    h["closing_balance"] = fg(closing)
    return h


def test_passes_and_boosts_confidence():
    p = ParsedStatement(header("1000.00", "910.00"), [row(0, wd="100.00", bal="900.00"), row(1, dep="10.00", bal="910.00")])
    v = validate_balances(p)
    assert v.status == "passed"
    assert v.computed_closing == D("910.00")
    assert p.rows[0].balance.confidence > 0.9


def test_detects_mismatch():
    p = ParsedStatement(header("1000.00", "900.00"), [row(0, wd="100.00", bal="950.00")])
    v = validate_balances(p)
    assert v.status == "failed"
    assert v.mismatched_rows == [0]
    assert p.rows[0].balance.confidence < 0.9
    assert "mismatch" in p.rows[0].issues[0]


def test_closing_mismatch_fails():
    p = ParsedStatement(header("1000.00", "999.00"), [row(0, wd="100.00", bal="900.00")])
    v = validate_balances(p)
    assert v.status == "failed" and v.mismatched_rows == []
    assert "differs" in v.note


def test_swaps_columns_when_balance_says_so():
    p = ParsedStatement(header("1000.00"), [row(0, dep="100.00", bal="900.00")])
    v = validate_balances(p)
    assert v.status == "passed"
    assert p.rows[0].withdrawal.value == D("100.00") and p.rows[0].deposit.value is None
    assert any("swapped" in i for i in p.rows[0].issues)


def test_resolves_unassigned_side():
    p = ParsedStatement(header("1000.00"), [row(0, unassigned="100.00", bal="1100.00"), row(1, unassigned="50.00", bal="1050.00")])
    validate_balances(p)
    assert p.rows[0].deposit.value == D("100.00")
    assert p.rows[1].withdrawal.value == D("50.00")
    assert p.rows[0].issues == []


def test_unresolvable_side_uses_hint_and_flags():
    p = ParsedStatement(header(None), [row(0, unassigned="100.00", bal=None, hint="cr")])
    validate_balances(p)
    assert p.rows[0].deposit.value == D("100.00")
    assert "uncertain" in p.rows[0].issues[0]


def test_derives_opening_from_first_row():
    p = ParsedStatement(header(None, "910.00"), [row(0, wd="100.00", bal="900.00"), row(1, dep="10.00", bal="910.00")])
    v = validate_balances(p)
    assert p.header["opening_balance"].value == D("1000.00")
    assert p.header["opening_balance"].source == "derived"
    assert v.status == "passed"


def test_no_rows_unavailable():
    assert validate_balances(ParsedStatement(header("1.00"), [])).status == "unavailable"


def test_missing_balances_unavailable():
    p = ParsedStatement(header(None), [row(0, wd="10.00", bal=None)])
    assert validate_balances(p).status == "unavailable"
