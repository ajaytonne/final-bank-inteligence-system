from datetime import date
from decimal import Decimal

import pytest

from app.services.normalize import (
    amount_side,
    clean_text,
    mask_account_number,
    parse_amount,
    parse_date,
)


@pytest.mark.parametrize(
    "text,expected",
    [
        ("03/09/2026", date(2026, 9, 3)),
        ("03-09-2026", date(2026, 9, 3)),
        ("03.09.26", date(2026, 9, 3)),
        ("2026-09-03", date(2026, 9, 3)),
        ("03 Sep 2026", date(2026, 9, 3)),
        ("03-Sept-2026", date(2026, 9, 3)),
        ("3 September 2026", date(2026, 9, 3)),
        ("Sep 3, 2026", date(2026, 9, 3)),
    ],
)
def test_parse_date_formats(text, expected):
    assert parse_date(text) == expected


def test_parse_date_monthfirst():
    assert parse_date("09/03/2026", dayfirst=False) == date(2026, 9, 3)


def test_parse_date_swaps_when_invalid():
    assert parse_date("09/25/2026") == date(2026, 9, 25)


@pytest.mark.parametrize("bad", [None, "", "32/13/2026", "hello", "99/99/99"])
def test_parse_date_invalid(bad):
    assert parse_date(bad) is None


@pytest.mark.parametrize(
    "text,expected",
    [
        ("1,35,000.00", Decimal("135000.00")),
        ("135,000.00", Decimal("135000.00")),
        ("715.44", Decimal("715.44")),
        ("₹ 2,500.50", Decimal("2500.50")),
        ("Rs. 99.00", Decimal("99.00")),
        ("INR 1,000", Decimal("1000.00")),
        ("1,200.00 Cr", Decimal("1200.00")),
        ("1,200.00 Dr", Decimal("-1200.00")),
        ("(450.00)", Decimal("-450.00")),
        ("-450.00", Decimal("-450.00")),
        ("1,2O0.00", Decimal("1200.00")),  # OCR O->0
    ],
)
def test_parse_amount(text, expected):
    assert parse_amount(text) == expected


@pytest.mark.parametrize("bad", [None, "", "-", "NIL", "TXN1234", "abc", "12345"])
def test_parse_amount_rejects(bad):
    assert parse_amount(bad) is None


def test_amount_side():
    assert amount_side("100.00 Cr") == "cr"
    assert amount_side("100.00 DR") == "dr"
    assert amount_side("100.00") is None


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("123456781234", "XXXXXXXX1234"),
        ("1234 5678 9012", "XXXXXXXX9012"),
        ("XXXXXXXX1234", "XXXXXXXX1234"),
        ("****5678", "XXXX5678"),
    ],
)
def test_mask_account_number(raw, expected):
    masked = mask_account_number(raw)
    assert masked == expected
    assert sum(c.isdigit() for c in masked) <= 4


@pytest.mark.parametrize("bad", [None, "", "abc", "12"])
def test_mask_account_number_invalid(bad):
    assert mask_account_number(bad) is None


def test_clean_text_drops_noise():
    assert clean_text("  ATM  ~ CASH | _  ") == "ATM CASH"
    assert clean_text(" ~ ") is None
