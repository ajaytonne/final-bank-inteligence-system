from datetime import date
from decimal import Decimal

from app.services.parser import (
    detect_columns,
    header_parts,
    parse_header,
    parse_row_columns,
    parse_row_positional,
    parse_statement,
)
from app.services.text_extraction import DocumentText, PageText, Word
from tests.conftest import make_line

HEADER = [(40, "Date"), (100, "Description"), (260, "Ref No"), (340, "Withdrawal"), (420, "Deposit"), (500, "Balance")]


def header_line(y=80):
    return make_line(HEADER, y=y)


def test_detect_columns_order():
    cols = detect_columns(header_line())
    assert [c.key for c in cols] == ["date", "description", "reference", "withdrawal", "deposit", "balance"]


def test_detect_columns_alt_names():
    line = make_line([(40, "Txn Date"), (100, "Narration"), (300, "Debit"), (380, "Credit"), (460, "Balance")])
    assert [c.key for c in detect_columns(line)] == ["date", "description", "withdrawal", "deposit", "balance"]


def test_detect_columns_value_date():
    line = make_line([(40, "Date"), (100, "Value Date"), (180, "Particulars"), (340, "Debit"), (420, "Credit"), (500, "Balance")])
    keys = [c.key for c in detect_columns(line)]
    assert keys[:3] == ["date", "value_date", "description"]


def test_detect_columns_effective_date():
    line = make_line([(40, "Tran Date"), (120, "Effective_Date"), (210, "Cheque Number"), (300, "Description"), (420, "Debit(INR)"), (500, "Credit(INR)"), (590, "Balance")])
    keys = [c.key for c in detect_columns(line)]
    assert keys[:3] == ["date", "effective_date", "reference"]


def test_detect_columns_rejects_plain_text():
    assert detect_columns(make_line([(40, "Opening Balance: 25,000.00")])) is None
    assert detect_columns(make_line([(40, "Statement Date"), (200, "Balance")])) is None


def test_header_parts_splits_merged_ocr_word():
    w = Word("Date___—Description", 0, 0, 190, 10, 40, 1)
    parts = [p for p, *_ in header_parts([w])]
    assert parts == ["Date", "Description"]


def test_parse_row_columns_deposit():
    cols = detect_columns(header_line())
    row_line = make_line([(40, "03/09/2026"), (100, "SALARY CREDIT ACME"), (260, "TXN62992312"), (410, "55,000.00"), (490, "80,000.00")])
    row = parse_row_columns(row_line, cols, 0, True)
    assert row.date.value == date(2026, 9, 3)
    assert row.description.value == "SALARY CREDIT ACME"
    assert row.reference.value == "TXN62992312"
    assert row.deposit.value == Decimal("55000.00")
    assert row.withdrawal.value is None
    assert row.balance.value == Decimal("80000.00")
    assert row.issues == []


def test_parse_row_columns_effective_date_and_empty_cheque():
    line = make_line([(40, "03/09/2026"), (120, "31/08/2026"), (300, "SMS Charges"), (430, "3.78"), (590, "3,138.84")])
    cols = detect_columns(make_line([(40, "Tran Date"), (120, "Effective_Date"), (210, "Cheque Number"), (300, "Description"), (420, "Debit(INR)"), (500, "Credit(INR)"), (590, "Balance")]))
    row = parse_row_columns(line, cols, 0, True)
    assert row.date.value == date(2026, 9, 3)
    assert row.effective_date.value == date(2026, 8, 31)
    assert row.reference.value is None
    assert row.withdrawal.value == Decimal("3.78")


def test_parse_row_columns_unreadable_amount():
    cols = detect_columns(header_line())
    row_line = make_line([(40, "03/09/2026"), (100, "ATM"), (350, "3,9l7.2x"), (490, "80,000.00")])
    row = parse_row_columns(row_line, cols, 0, True)
    assert row.withdrawal.value is None
    assert any("Unreadable" in i for i in row.issues)


def test_parse_row_columns_no_date_returns_none():
    cols = detect_columns(header_line())
    assert parse_row_columns(make_line([(100, "MONTHLY PAYMENT")]), cols, 0, True) is None


def test_parse_row_positional_unassigned():
    line = make_line([(40, "05/09/2026"), (100, "ATM CASH BANER"), (260, "TXN88220482"), (350, "3,917.26"), (490, "1,31,082.74")])
    row = parse_row_positional(line, 0, True)
    assert row.unassigned == Decimal("3917.26")
    assert row.balance.value == Decimal("131082.74")
    assert row.reference.value == "TXN88220482"
    assert row.description.value == "ATM CASH BANER"
    assert row.balance.confidence < 0.95  # no layout


def test_parse_row_positional_three_amounts():
    line = make_line([(40, "05/09/2026"), (100, "X"), (350, "10.00"), (420, "0.00"), (490, "90.00")])
    row = parse_row_positional(line, 0, True)
    assert row.withdrawal.value == Decimal("10.00")
    assert row.balance.value == Decimal("90.00")


def test_parse_header_segments_and_pairs():
    lines = [
        make_line([(40, "Account Holder:"), (130, "Priya Sharma"), (320, "Account Number: 123456781234")], y=10),
        make_line([(40, "Statement Period: 01/09/2026 to 30/09/2026")], y=30),
        make_line([(40, "Opening Balance: 25,000.00")], y=50),
        make_line([(40, "Closing Balance: 1,46,623.97")], y=500),
    ]
    h = parse_header(lines, True)
    assert h["account_holder"].value == "Priya Sharma"
    assert h["account_number_masked"].value == "XXXXXXXX1234"
    assert "masked" in h["account_number_masked"].note
    assert h["period_start"].value == date(2026, 9, 1)
    assert h["period_end"].value == date(2026, 9, 30)
    assert h["opening_balance"].value == Decimal("25000.00")
    assert h["closing_balance"].value == Decimal("146623.97")


def test_parse_header_missing_fields_stay_none():
    h = parse_header([make_line([(40, "Random text only")])], True)
    assert all(f.value is None for f in h.values())


def test_parse_additional_bank_and_account_fields():
    lines = [
        make_line([(40, "To:")], y=10),
        make_line([(40, "Priya Sharma")], y=20),
        make_line([(40, "YOUR BRANCH DETAILS")], y=30),
        make_line([(40, "Kalyan")], y=40),
        make_line([(40, "IFSC: ABCD0123456")], y=50),
        make_line([(40, "Account Type: SAVING BANK A/C")], y=60),
        make_line([(40, "STATEMENT OF ACCOUNT FOR THE PERIOD OF 01/09/2026 to 30/09/2026")], y=70),
        make_line([(40, "Account Number 123456781234")], y=80),
        make_line([(40, "Copyright Example Small Finance Bank | Call us")], y=90),
    ]
    h = parse_header(lines, True)
    assert h["bank_name"].value == "Example Small Finance Bank"
    assert h["branch_name"].value == "Kalyan"
    assert h["account_holder"].value == "Priya Sharma"
    assert h["account_number_masked"].value == "XXXXXXXX1234"
    assert h["account_type"].value == "Saving Bank A/C"
    assert h["ifsc"].value == "ABCD0123456"
    assert h["period_start"].value == date(2026, 9, 1)


def test_parse_header_low_conf_name():
    h = parse_header([make_line([(40, "Customer Name: Pr1ya #Sharma")])], True)
    assert h["account_holder"].confidence < 0.95
    assert h["account_holder"].note


def test_parse_statement_continuation_and_summary():
    lines = [
        header_line(80),
        make_line([(40, "Opening Balance"), (490, "1,000.00")], y=95),
        make_line([(40, "01/09/2026"), (100, "NEFT RENT"), (350, "100.00"), (490, "900.00")], y=110),
        make_line([(100, "MONTHLY PAYMENT")], y=122),
        make_line([(40, "02/09/2026"), (100, "INTEREST"), (420, "10.00"), (490, "910.00")], y=140),
        make_line([(40, "Total"), (350, "100.00"), (420, "10.00")], y=160),
        make_line([(40, "Page 1")], y=800),
    ]
    doc = DocumentText([PageText(1, "pdf_text", lines)])
    parsed = parse_statement(doc)
    assert len(parsed.rows) == 2
    assert parsed.rows[0].description.value == "NEFT RENT MONTHLY PAYMENT"
    assert parsed.rows[1].deposit.value == Decimal("10.00")
    assert parsed.header["opening_balance"].value == Decimal("1000.00")


def test_parse_statement_reuses_columns_across_pages():
    p1 = [header_line(80), make_line([(40, "01/09/2026"), (100, "A"), (350, "100.00"), (490, "900.00")], y=110)]
    p2 = [make_line([(40, "02/09/2026"), (100, "B"), (420, "50.00"), (490, "950.00")], y=60, page=2)]
    doc = DocumentText([PageText(1, "pdf_text", p1), PageText(2, "pdf_text", p2)])
    rows = parse_statement(doc).rows
    assert rows[1].deposit.value == Decimal("50.00")
    assert rows[1].page == 2
