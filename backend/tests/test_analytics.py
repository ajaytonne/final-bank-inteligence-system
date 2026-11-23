import datetime as dt
from decimal import Decimal

import pytest

from statement_analyser.services.analytics import analyse_transactions, rows_from


def tx(date, desc, dep=None, wd=None, bal=None):
    return {"date": date, "description": desc, "deposit": dep, "withdrawal": wd, "balance": bal}


BASE = [
    tx("2026-07-01", "SALARY CREDIT ACME PVT LTD", dep="50000", bal="60000"),
    tx("2026-07-05", "NACH DR HDFC LOAN EMI 12345", wd="8000", bal="52000"),
    tx("2026-07-10", "CASH DEPOSIT CDM", dep="60000", bal="112000"),
    tx("2026-07-12", "NEFT TO RAMESH KUMAR", wd="20000", bal="92000"),
    tx("2026-07-13", "NEFT FROM RAMESH KUMAR", dep="20000", bal="112000"),
    tx("2026-08-01", "SALARY CREDIT ACME PVT LTD", dep="50000", bal="150000"),
    tx("2026-08-05", "NACH DR HDFC LOAN EMI 67890", wd="8000", bal="142000"),
    tx("2026-08-20", "CHQ RETURN INSUFFICIENT FUNDS", wd="500", bal="141500"),
]


@pytest.fixture(scope="module")
def r():
    return analyse_transactions(BASE)


def test_totals_and_period(r):
    assert r["totals"] == {"credits": "180000.00", "debits": "36500.00", "credit_count": 4, "debit_count": 4, "net": "143500.00"}
    assert r["period"] == {"start": "2026-07-01", "end": "2026-08-20"} and r["transaction_count"] == 8


def test_monthly_view(r):
    july, aug = r["monthly"]
    assert (july["month"], july["credits"], july["debits"], july["net"]) == ("2026-07", "130000.00", "28000.00", "102000.00")
    assert (july["min_balance"], july["max_balance"]) == ("52000.00", "112000.00")
    assert aug["credit_count"] == 1 and aug["debit_count"] == 2


def test_end_of_day_balance_is_carried_over_quiet_days(r):
    b = r["balances"]
    assert b["days_covered"] == 51  # 1 Jul .. 20 Aug, every day counted
    assert (b["min_balance"], b["max_balance"], b["closing_balance"]) == ("52000.00", "150000.00", "141500.00")
    assert b["min_balance_date"] == "2026-07-05"
    # 5 Jul..9 Jul all sit at 52,000: the average must weigh days, not transactions
    assert Decimal(b["average_daily_balance"]) != Decimal("100000.00")


def test_average_balance_exact_on_a_tiny_case():
    out = analyse_transactions([tx("2026-01-01", "A", dep="100", bal="100"), tx("2026-01-03", "B", wd="40", bal="60")])
    assert out["balances"]["average_daily_balance"] == "86.67"  # (100 + 100 + 60) / 3 days


def test_salary_and_regularity(r):
    s = r["salary"]
    assert s["detected"] and s["average_amount"] == "50000.00" and s["months_with_salary"] == 2 and s["regularity"] == 1.0


def test_salary_regularity_drops_when_a_month_is_missing():
    rows = BASE[:5] + [tx("2026-09-02", "UPI/TEA", wd="10", bal="1")]
    s = analyse_transactions(rows)["salary"]
    assert s["months_in_period"] == 2 and s["months_with_salary"] == 1 and s["regularity"] == 0.5


def test_emi_is_found_even_though_the_mandate_number_changes(r):
    e = r["emi"]
    assert len(e["obligations"]) == 1
    ob = e["obligations"][0]
    assert ob["amount"] == "8000.00" and ob["months"] == ["2026-07", "2026-08"] and ob["rows"] == [2, 7]
    assert e["monthly_obligation"] == "8000.00" and e["obligation_to_salary"] == 0.16


def test_a_single_emi_is_reported_but_not_counted_as_a_monthly_obligation():
    out = analyse_transactions([tx("2026-07-05", "NACH DR LOAN EMI", wd="8000", bal="1")])
    assert out["emi"]["obligations"][0]["basis"].endswith("seen once") and out["emi"]["monthly_obligation"] == "0.00"


def test_same_amount_twice_without_a_loan_word_is_not_an_emi():
    out = analyse_transactions([tx("2026-07-05", "UPI/GYM", wd="999", bal="1"), tx("2026-08-05", "UPI/GYM", wd="999", bal="1")])
    assert out["emi"]["obligations"] == []


def test_same_amount_three_months_running_is_an_emi_candidate():
    rows = [tx(f"2026-0{m}-05", "ACME FINANCE", wd="4500", bal="1") for m in (5, 6, 7)]
    ob = analyse_transactions(rows)["emi"]["obligations"]
    assert len(ob) == 1 and ob[0]["basis"] == "same amount every month"


def test_bounces(r):
    b = r["bounces"]
    assert b["count"] == 1 and b["events"][0]["row"] == 8 and b["events"][0]["amount"] == "500.00"


@pytest.mark.parametrize("text", ["SALARY RETURN OF EXCESS", "UPI/RETURN GIFT SHOP", "RETAIL STORE"])
def test_ordinary_words_are_not_bounces(text):
    assert analyse_transactions([tx("2026-07-05", text, wd="100", bal="1")])["bounces"]["count"] == 0


def test_cash_deposits_and_the_large_cash_flag(r):
    c = r["cash"]
    assert c["deposit_count"] == 1 and c["deposits_total"] == "60000.00"
    assert [d["row"] for d in c["large_deposits"]] == [3]
    small = analyse_transactions([tx("2026-07-10", "CASH DEPOSIT", dep="49999.99", bal="1")])["cash"]
    assert small["large_deposits"] == []


def test_atm_withdrawals():
    out = analyse_transactions([tx("2026-07-10", "ATM CASH WITHDRAWAL", wd="5000", bal="1")])["cash"]
    assert out["withdrawal_count"] == 1 and out["withdrawals_total"] == "5000.00"


def test_circular_transfer_is_found_and_ignores_strangers(r):
    c = r["circular"]
    assert c["count"] == 1 and c["pairs"][0]["out_row"] == 4 and c["pairs"][0]["in_row"] == 5 and c["pairs"][0]["days_apart"] == 1
    other = [tx("2026-07-12", "NEFT TO RAMESH KUMAR", wd="20000", bal="1"), tx("2026-07-13", "NEFT FROM SURESH PATEL", dep="20000", bal="1")]
    assert analyse_transactions(other)["circular"]["count"] == 0
    slow = [tx("2026-07-01", "NEFT TO RAMESH KUMAR", wd="20000", bal="1"), tx("2026-07-20", "NEFT FROM RAMESH KUMAR", dep="20000", bal="1")]
    assert analyse_transactions(slow)["circular"]["count"] == 0


def test_largest_movements(r):
    assert r["largest"]["credits"][0]["amount"] == "60000.00" and r["largest"]["debits"][0]["row"] == 4


def test_empty_and_balance_less_statements_do_not_break():
    e = analyse_transactions([])
    assert e["transaction_count"] == 0 and e["balances"] is None and e["monthly"] == [] and e["salary"]["detected"] is False
    nb = analyse_transactions([tx("2026-07-01", "X", dep="10"), tx("2026-07-02", "Y", wd="5")])
    assert nb["balances"] is None and nb["totals"]["net"] == "5.00"


def test_rows_without_dates_are_still_counted_in_totals():
    out = analyse_transactions([tx(None, "SALARY", dep="100"), tx("2026-07-02", "X", wd="5")])
    assert out["totals"]["credits"] == "100.00" and out["salary"]["months_with_salary"] == 0


def test_accepts_extracted_and_reviewed_objects(text_pdf):
    from statement_analyser.services.file_validation import validate_upload
    from statement_analyser.services.pipeline import run_extraction
    from statement_analyser.config import Settings

    res = run_extraction(validate_upload("s.pdf", text_pdf, 10**7), Settings())
    rows = rows_from(res.transactions)
    assert len(rows) == 14 and all(isinstance(r.date, dt.date) for r in rows)
    out = analyse_transactions(res.transactions, res.header.period_start.value, res.header.period_end.value)
    assert out["transaction_count"] == 14 and out["salary"]["detected"] is True
