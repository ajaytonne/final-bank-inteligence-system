import copy
import datetime as dt
from decimal import Decimal

import pytest

from statement_analyser.services.reconciliation_engine import (
    INTER_BANK,
    INTERNAL,
    Side,
    Txn,
    build_summary,
    check_accounts,
    consolidate,
    reconcile,
    similarity,
)

D = dt.date.fromisoformat


def side(sid, txns, bank="HDFC Bank", last4="2222", start="2026-09-01", end="2026-09-30", owned=False, label=None):
    """txns: (date, description, reference, amount, "debit"/"credit")"""
    return Side(sid, label or f"S{sid}", bank, last4, D(start) if start else None, D(end) if end else None,
                [Txn(i, D(t[0]) if t[0] else None, t[1], t[2], Decimal(t[3]), t[4]) for i, t in enumerate(txns)], owned=owned)


def by_status(out, status):
    return [r for r in out["rows"] if r["status"] == status]


def only(out, status):
    rows = by_status(out, status)
    assert len(rows) == 1, [(r["status"], r["reason"]) for r in out["rows"]]
    return rows[0]


# ---- inter-bank: references, amounts, dates ---------------------------------------------------
def test_exact_reference_match_across_banks():
    a = side(1, [("2026-09-05", "NEFT TO HDFC", "UTR9001", "10000.00", "debit")], bank="State Bank of India", last4="1111")
    b = side(2, [("2026-09-05", "NEFT FROM SBI", "UTR9001", "10000.00", "credit")])
    row = only(reconcile(a, b, INTER_BANK, 2), "Matched")
    assert row["match_type"] == "Reference" and row["confidence"] >= 0.95 and row["confirmation_status"] == "auto"
    assert "same reference UTR9001" in row["reason"].lower() or "Same reference UTR9001" in row["reason"]
    assert (row["a_index"], row["b_index"]) == (0, 0)


def test_reconciliation_refuses_different_currencies():
    a = side(1, [], bank="SBI", last4="1111")
    b = side(2, [], bank="HDFC", last4="2222")
    b.currency = "USD"
    assert check_accounts(INTER_BANK, a, b) == "Cannot compare statements with different currencies. Convert both to the same currency first."


def test_reference_beats_a_better_looking_description():
    a = side(1, [("2026-09-05", "NEFT TO RAMESH KUMAR", "R1", "1000.00", "debit")], bank="SBI", last4="1111")
    b = side(2, [("2026-09-05", "NEFT FROM RAMESH KUMAR", "R2", "1000.00", "credit"), ("2026-09-05", "CREDIT", "R1", "1000.00", "credit")])
    out = reconcile(a, b, INTER_BANK, 2)
    row = only(out, "Matched")
    assert row["match_type"] == "Reference" and row["b_index"] == 1  # matched on the reference, not the lookalike narration
    assert [r["b_index"] for r in by_status(out, "Unmatched")] == [0]


def test_transfer_settles_next_day_is_a_timing_difference():
    a = side(1, [("2026-09-05", "NEFT TO HDFC", "UTR9", "10000.00", "debit")], bank="SBI", last4="1111")
    b = side(2, [("2026-09-06", "NEFT FROM SBI", "UTR9", "10000.00", "credit")])
    row = only(reconcile(a, b, INTER_BANK, 2), "Timing Difference")
    assert "dates differ by 1 day" in row["reason"] and row["confidence"] >= 0.9


def test_date_window_decides_whether_it_matches():
    a = side(1, [("2026-09-05", "TRANSFER TO RAMESH KUMAR", "", "2500.00", "debit")], bank="SBI", last4="1111")
    b = side(2, [("2026-09-08", "TRANSFER FROM RAMESH KUMAR", "", "2500.00", "credit")])
    narrow = reconcile(a, b, INTER_BANK, 2)
    assert {r["status"] for r in narrow["rows"]} == {"Unmatched"}  # 3 days apart, window 2
    wide = reconcile(a, b, INTER_BANK, 3)
    assert only(wide, "Timing Difference")["status"] == "Timing Difference"
    same_day = reconcile(a, side(2, [("2026-09-05", "TRANSFER FROM RAMESH KUMAR", "", "2500.00", "credit")]), INTER_BANK, 0)
    assert only(same_day, "Matched")["confirmation_status"] == "auto"


def test_same_reference_but_dates_too_far_apart_goes_to_manual_review():
    a = side(1, [("2026-09-05", "NEFT", "UTR5", "900.00", "debit")], bank="SBI", last4="1111")
    b = side(2, [("2026-09-20", "NEFT", "UTR5", "900.00", "credit")])
    row = only(reconcile(a, b, INTER_BANK, 3), "Manual Review")
    assert "UTR5" in row["reason"] and "15 days apart" in row["reason"] and row["confirmation_status"] == "pending"


def test_same_reference_but_different_amount_goes_to_manual_review():
    a = side(1, [("2026-09-05", "NEFT", "UTR6", "900.00", "debit")], bank="SBI", last4="1111")
    b = side(2, [("2026-09-05", "NEFT", "UTR6", "950.00", "credit")])
    row = only(reconcile(a, b, INTER_BANK, 3), "Manual Review")
    assert "amounts differ" in row["reason"]


def test_equal_amounts_alone_never_make_a_match():
    a = side(1, [("2026-09-05", "ELECTRICITY BILL MSEDCL", "", "777.00", "debit")], bank="SBI", last4="1111")
    b = side(2, [("2026-09-05", "SALARY ACME PVT LTD", "", "777.00", "credit")])
    out = reconcile(a, b, INTER_BANK, 3)
    row = only(out, "Possible Match")
    assert row["match_type"] == "Amount only" and row["confidence"] < 0.5 and row["confirmation_status"] == "pending"
    assert not by_status(out, "Matched") and not by_status(out, "Timing Difference")
    assert "amount alone is not enough" in row["reason"]


def test_a_debit_only_pairs_with_a_credit_between_banks():
    a = side(1, [("2026-09-05", "NEFT TO X", "", "500.00", "debit")], bank="SBI", last4="1111")
    b = side(2, [("2026-09-05", "NEFT TO X", "", "500.00", "debit")])  # two debits: not a transfer pair
    assert {r["status"] for r in reconcile(a, b, INTER_BANK, 3)["rows"]} == {"Unmatched"}


def test_several_candidates_with_the_same_evidence_need_manual_review():
    a = side(1, [("2026-09-05", "TRANSFER", "", "500.00", "debit")], bank="SBI", last4="1111")
    b = side(2, [("2026-09-05", "TRANSFER", "", "500.00", "credit"), ("2026-09-05", "TRANSFER", "", "500.00", "credit")])
    out = reconcile(a, b, INTER_BANK, 2)
    rows = by_status(out, "Manual Review")
    assert len(rows) == 2 and all("identical evidence" in r["reason"] for r in rows)
    assert not by_status(out, "Matched") and all(r["confirmation_status"] == "pending" for r in rows)


def test_a_transaction_is_never_used_by_two_pairs():
    a = side(1, [("2026-09-05", "TRANSFER TO RAMESH", "", "100.00", "debit"), ("2026-09-06", "TRANSFER TO RAMESH", "", "100.00", "debit")],
             bank="SBI", last4="1111")
    b = side(2, [("2026-09-05", "TRANSFER FROM RAMESH", "", "100.00", "credit")])
    out = reconcile(a, b, INTER_BANK, 3)
    pairs = [r for r in out["rows"] if r["a_index"] is not None and r["b_index"] is not None]
    assert len(pairs) == 1 and pairs[0]["a_index"] == 0  # the same-day one wins (better evidence)
    assert [r["a_index"] for r in by_status(out, "Unmatched")] == [1]


def test_missing_references_fall_back_to_description_and_date():
    a = side(1, [("2026-09-05", "IMPS/RAMESH KUMAR/RENT SEP", "", "12000.00", "debit")], bank="SBI", last4="1111")
    b = side(2, [("2026-09-05", "IMPS/RAMESH KUMAR/RENT SEP", "", "12000.00", "credit")])
    row = only(reconcile(a, b, INTER_BANK, 2), "Matched")
    assert row["match_type"] == "Amount + description" and 0.8 <= row["confidence"] < 0.95


def test_partly_similar_description_is_only_a_possible_match():
    a = side(1, [("2026-09-05", "NEFT PAYMENT ACME", "", "4000.00", "debit")], bank="SBI", last4="1111")
    b = side(2, [("2026-09-05", "CREDIT ACME REFUND", "", "4000.00", "credit")])
    row = only(reconcile(a, b, INTER_BANK, 2), "Possible Match")
    assert row["match_type"] == "Description + date" and row["confirmation_status"] == "pending"


def test_unmatched_outgoing_and_incoming_are_reported_separately():
    a = side(1, [("2026-09-05", "NEFT TO SOMEONE", "", "321.00", "debit")], bank="SBI", last4="1111")
    b = side(2, [("2026-09-06", "SALARY", "", "50000.00", "credit")])
    out = reconcile(a, b, INTER_BANK, 2)
    outgoing, incoming = (only(out, "Unmatched") if False else r for r in sorted(out["rows"], key=lambda r: r["a_index"] is None))
    assert "outgoing (debit)" in outgoing["reason"] and "looks like a transfer" in outgoing["reason"] and outgoing["b_index"] is None
    assert "incoming (credit)" in incoming["reason"] and incoming["a_index"] is None
    assert all(r["confirmation_status"] == "none" for r in out["rows"])


def test_inter_bank_ignores_transactions_outside_the_other_statements_period():
    a = side(1, [("2026-08-20", "NEFT TO X", "", "700.00", "debit")], bank="SBI", last4="1111", start="2026-08-01", end="2026-08-31")
    b = side(2, [("2026-09-20", "NEFT FROM Y", "", "700.00", "credit")])
    out = reconcile(a, b, INTER_BANK, 3)
    assert {r["match_type"] for r in out["rows"]} == {"Period gap"}  # not compared, not an error
    assert build_summary(out["rows"], 1, 1)["unmatched"] == 0 and build_summary(out["rows"], 1, 1)["period_gaps"] == 2


# ---- internal (same account) -------------------------------------------------------------------
def _txns(*items):
    return [(d, desc, ref, amt, "debit") for d, desc, ref, amt in items]


def test_internal_overlapping_statements():
    common = [("2026-09-16", "UPI/SWIGGY/1", "R1", "350.00"), ("2026-09-20", "ATM CASH", "R2", "2000.00")]
    a = side(1, _txns(("2026-09-03", "RENT", "R0", "15000.00"), *common, ("2026-09-25", "UPI/ZOMATO/9", "R9", "410.00")),
             start="2026-09-01", end="2026-09-30")
    b = side(2, _txns(*common, ("2026-10-05", "ELECTRICITY BILL", "R7", "900.00")), start="2026-09-15", end="2026-10-15")
    out = reconcile(a, b, INTERNAL, 0)
    assert len(by_status(out, "Matched")) == 2
    missing = only(out, "Missing Transaction")  # inside the overlap (15 Sep - 30 Sep) but absent from B
    assert (missing["a_index"], "statement B" in missing["reason"]) == (3, True)
    gaps = [r for r in out["rows"] if r["match_type"] == "Period gap"]
    assert sorted([(r["a_index"], r["b_index"]) for r in gaps], key=str) == [(0, None), (None, 2)]  # 3 Sep and 5 Oct: outside the overlap
    assert "Overlapping period: 2026-09-15 to 2026-09-30" in out["notes"][0]
    summary = build_summary(out["rows"], 4, 3)
    assert (summary["matched"], summary["missing_transactions"], summary["unmatched"], summary["period_gaps"]) == (2, 1, 1, 2)


def test_internal_statements_with_different_periods_are_not_errors():
    a = side(1, _txns(("2026-09-05", "RENT", "R1", "100.00")), start="2026-09-01", end="2026-09-30")
    b = side(2, _txns(("2026-11-05", "RENT", "R1", "100.00")), start="2026-11-01", end="2026-11-30")
    out = reconcile(a, b, INTERNAL, 0)
    assert {r["match_type"] for r in out["rows"]} == {"Period gap"} and not by_status(out, "Missing Transaction")
    assert "do not overlap" in out["notes"][0]


def test_internal_needs_the_same_direction():
    a = side(1, [("2026-09-05", "X", "", "100.00", "debit")])
    b = side(2, [("2026-09-05", "X", "", "100.00", "credit")])
    assert not by_status(reconcile(a, b, INTERNAL, 0), "Matched")


def test_duplicate_statement_upload_matches_every_row():
    rows = [("2026-09-03", "SALARY ACME", "T1", "55000.00", "credit"), ("2026-09-04", "UPI/SWIGGY/1", "T2", "350.00", "debit"),
            ("2026-09-06", "NEFT RENT", "T3", "15000.00", "debit")]
    out = reconcile(side(1, rows), side(2, rows), INTERNAL, 0)
    assert len(by_status(out, "Matched")) == 3 and len(out["rows"]) == 3
    assert any("second upload" in n for n in out["notes"])


def test_exact_twins_in_both_statements_are_left_for_a_person():
    twin = ("2026-09-04", "CASH DEPOSIT", "", "1000.00", "credit")
    out = reconcile(side(1, [twin, twin]), side(2, [twin, twin]), INTERNAL, 0)
    assert len(by_status(out, "Manual Review")) >= 2 and not by_status(out, "Matched")
    assert len(by_status(out, "Duplicate Candidate")) == 2  # one inside each statement


def test_duplicate_candidates_are_shown_not_deleted():
    t = ("2026-09-04", "UPI/SWIGGY/1", "R1", "350.00", "debit")
    a = side(1, [t, t, ("2026-09-05", "ATM", "R5", "100.00", "debit")])
    before = len(a.txns)
    out = reconcile(a, side(2, []), INTERNAL, 0)
    dup = only(out, "Duplicate Candidate")
    assert (dup["a_index"], dup["b_index"], dup["a_statement_id"], dup["b_statement_id"]) == (0, 1, 1, 1)
    assert "nothing is deleted" in dup["reason"] and dup["confirmation_status"] == "pending" and len(a.txns) == before


def test_same_amount_with_different_references_is_not_a_duplicate():
    a = side(1, [("2026-09-04", "ATM CASH", "R1", "500.00", "debit"), ("2026-09-04", "ATM CASH", "R2", "500.00", "debit")])
    assert not by_status(reconcile(a, side(2, []), INTERNAL, 0), "Duplicate Candidate")


def test_a_missing_date_cannot_be_a_confirmed_match():
    a = side(1, [(None, "NEFT TO X", "U1", "100.00", "debit")], bank="SBI", last4="1111")
    b = side(2, [("2026-09-05", "NEFT FROM Y", "U1", "100.00", "credit")])
    row = only(reconcile(a, b, INTER_BANK, 3), "Possible Match")
    assert "date is missing" in row["reason"]


# ---- internal transfers and totals -------------------------------------------------------------
def test_internal_transfer_needs_both_accounts_confirmed_as_yours():
    rows = [("2026-09-05", "NEFT TO HDFC SELF", "U1", "10000.00", "debit")]
    other = [("2026-09-05", "NEFT FROM SBI SELF", "U1", "10000.00", "credit")]
    unknown = reconcile(side(1, rows, bank="SBI", last4="1111"), side(2, other), INTER_BANK, 2)
    assert only(unknown, "Matched")["internal_transfer"] == 0  # matched, but ownership is not confirmed: no self-transfer claim
    mine = reconcile(side(1, rows, bank="SBI", last4="1111", owned=True), side(2, other, owned=True), INTER_BANK, 2)
    row = only(mine, "Matched")
    assert row["internal_transfer"] == 1 and "possible internal transfer" in row["reason"] and row["confirmation_status"] == "auto"


def test_amount_only_pair_is_never_called_an_internal_transfer():
    a = side(1, [("2026-09-05", "RENT", "", "777.00", "debit")], bank="SBI", last4="1111", owned=True)
    b = side(2, [("2026-09-05", "SALARY", "", "777.00", "credit")], owned=True)
    assert only(reconcile(a, b, INTER_BANK, 2), "Possible Match")["internal_transfer"] == 0


def test_only_confirmed_internal_transfers_leave_the_consolidated_totals():
    a = side(1, [("2026-09-05", "NEFT TO HDFC SELF", "U1", "10000.00", "debit"), ("2026-09-06", "SWIGGY", "", "400.00", "debit")], bank="SBI", last4="1111", owned=True)
    b = side(2, [("2026-09-05", "NEFT FROM SBI SELF", "U1", "10000.00", "credit"), ("2026-09-08", "SALARY", "", "50000.00", "credit")], owned=True)
    rows = reconcile(a, b, INTER_BANK, 2)["rows"]
    for r in rows:  # the engine returns rows as the store would
        r["internal_transfer"] = r["internal_transfer"]
    before = consolidate([a, b], rows)
    assert (before["income"], before["expenses"], before["excluded_transfer_count"]) == ("60000.00", "10400.00", 0)  # nothing excluded yet
    next(r for r in rows if r["status"] == "Matched")["confirmation_status"] = "confirmed"  # the user confirms
    after = consolidate([a, b], rows)
    assert (after["income"], after["expenses"], after["savings"]) == ("50000.00", "400.00", "49600.00")
    assert (after["excluded_transfer_count"], after["excluded_amount"], after["income_before_exclusion"]) == (1, "10000.00", "60000.00")


def test_summary_numbers():
    a = side(1, [("2026-09-05", "NEFT TO RAMESH KUMAR", "U1", "1000.00", "debit"), ("2026-09-06", "CASH", "", "200.00", "debit"),
                 ("2026-09-07", "ODD", "", "55.00", "debit")], bank="SBI", last4="1111")
    b = side(2, [("2026-09-05", "NEFT FROM RAMESH KUMAR", "U1", "1000.00", "credit"), ("2026-09-06", "DEPOSIT", "", "200.00", "credit"),
                 ("2026-09-09", "SALARY", "", "9000.00", "credit")])
    out = reconcile(a, b, INTER_BANK, 2)
    s = build_summary(out["rows"], 3, 3)
    assert (s["total_a"], s["total_b"], s["matched"], s["possible_matches"], s["unmatched"]) == (3, 3, 1, 1, 2)
    assert (s["total_matched_amount"], s["total_unmatched_amount"]) == ("1000.00", "9055.00")  # matched once; amount-only pair is not "matched"


# ---- inputs and safety -------------------------------------------------------------------------
def test_engine_does_not_modify_its_input():
    a = side(1, [("2026-09-05", "NEFT TO RAMESH", "U1", "1000.00", "debit"), ("2026-09-05", "ATM", "", "10.00", "debit")], bank="SBI", last4="1111")
    b = side(2, [("2026-09-05", "NEFT FROM RAMESH", "U1", "1000.00", "credit")])
    snapshot = (copy.deepcopy(a), copy.deepcopy(b))
    reconcile(a, b, INTER_BANK, 3)
    assert (a, b) == snapshot


def test_account_checks():
    sbi = side(1, [], bank="SBI", last4="1111")
    hdfc = side(2, [], bank="HDFC", last4="2222")
    assert "same bank account" in check_accounts(INTERNAL, sbi, hdfc)
    assert check_accounts(INTER_BANK, sbi, hdfc) is None
    assert check_accounts(INTERNAL, sbi, side(3, [], bank="sbi", last4="1111")) is None
    assert "same account" in check_accounts(INTER_BANK, sbi, side(3, [], bank="SBI", last4="1111"))
    assert check_accounts(INTER_BANK, sbi, side(4, [], bank="", last4="")) is None  # not enough information: allowed
    sbi.account_id, hdfc.account_id = 7, 7  # an explicit assignment wins over the statement header
    assert "same account" in check_accounts(INTER_BANK, sbi, hdfc)


def test_similarity_ignores_ids_and_payment_codes():
    assert similarity("UPI/P2M/98372/AMAZON", "POS/AMAZON/STORE01") == 1.0
    assert similarity("RENT", "SALARY") < 0.3 and similarity("", "x") == 0.0


@pytest.mark.parametrize("window", [0, 1, 2, 3, 5, 7])
def test_every_window_option_works(window):
    a = side(1, [("2026-09-05", "TRANSFER TO RAMESH KUMAR", "", "100.00", "debit")], bank="SBI", last4="1111")
    b = side(2, [("2026-09-12", "TRANSFER FROM RAMESH KUMAR", "", "100.00", "credit")])  # 7 days apart
    out = reconcile(a, b, INTER_BANK, window)
    assert bool(by_status(out, "Timing Difference")) == (window >= 7)
