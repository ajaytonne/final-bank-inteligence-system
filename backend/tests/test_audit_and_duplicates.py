import datetime as dt
from decimal import Decimal

from statement_analyser.schemas import ReviewedHeader, ReviewedStatement, ReviewedTransaction
from statement_analyser.services.audit_log import AuditLog
from statement_analyser.services.duplicate_check import check_statement


def stmt(name="a.pdf", last4="1234", start="2026-09-01", end="2026-09-30", rows=None, bank="Demo Bank"):
    rows = rows if rows is not None else [("2026-09-02", "UPI/SWIGGY", "450.00"), ("2026-09-05", "RENT", "15000.00")]
    return ReviewedStatement(
        file_name=name,
        header=ReviewedHeader(bank_name=bank, account_number_masked=f"XXXXXXXX{last4}",
                              period_start=dt.date.fromisoformat(start), period_end=dt.date.fromisoformat(end)),
        transactions=[ReviewedTransaction(date=d, description=desc, withdrawal=Decimal(a)) for d, desc, a in rows],
    )


# ---- duplicate checks ----------------------------------------------------------------------------
def test_exact_duplicate_is_found_even_when_rows_are_reordered():
    old = stmt()
    new = stmt("copy.pdf", rows=[("2026-09-05", "rent", "15000.00"), ("2026-09-02", "UPI/SWIGGY", "450.00")])
    w = check_statement(new, [(7, old)])
    assert [x.kind for x in w] == ["duplicate"] and w[0].statement_id == 7 and "#7" in w[0].message


def test_overlapping_period_same_account():
    old = stmt()
    new = stmt("oct.pdf", start="2026-09-20", end="2026-10-20", rows=[("2026-10-02", "X", "10.00")])
    w = check_statement(new, [(1, old)])
    assert [x.kind for x in w] == ["overlap"] and "11 day" in w[0].message


def test_different_account_or_bank_gives_no_warning():
    old = stmt()
    assert check_statement(stmt("b.pdf", last4="9999"), [(1, old)]) == []
    assert check_statement(stmt("c.pdf", bank="Other Bank"), [(1, old)]) == []


def test_next_month_does_not_overlap():
    new = stmt("oct.pdf", start="2026-10-01", end="2026-10-31", rows=[("2026-10-02", "X", "10.00")])
    assert check_statement(new, [(1, stmt())]) == []


def test_missing_account_number_never_matches():
    old = stmt(last4="")
    assert check_statement(stmt(last4=""), [(1, old)]) == []


def test_repeated_rows_in_one_statement():
    rows = [("2026-09-02", "UPI/TEA", "20.00"), ("2026-09-02", "upi/tea", "20.00"), ("2026-09-03", "UPI/TEA", "20.00")]
    w = check_statement(stmt(rows=rows), [])
    assert [x.kind for x in w] == ["repeated_rows"] and "1 transaction" in w[0].message


def test_empty_statement_is_not_a_duplicate_of_another_empty_one():
    kinds = [x.kind for x in check_statement(stmt(rows=[]), [(1, stmt(rows=[]))])]
    assert "duplicate" not in kinds


# ---- audit log -----------------------------------------------------------------------------------
def test_audit_log_records_and_filters(tmp_path):
    log = AuditLog(str(tmp_path / "a.db"))

    class Ch:
        where, field, old, new = "Row 2", "withdrawal", "450.00", "540.00"

    log.record("saved", 1, "a.pdf (2 transactions)", [Ch()])
    log.record("deleted", 2, "b.pdf")
    assert [e["action"] for e in log.list()] == ["deleted", "edited", "saved"]  # newest first
    only1 = log.list(1)
    assert {e["statement_id"] for e in only1} == {1}
    edit = next(e for e in only1 if e["action"] == "edited")
    assert (edit["where"], edit["field"], edit["old"], edit["new"]) == ("Row 2", "withdrawal", "450.00", "540.00")


# ---- API -----------------------------------------------------------------------------------------
def body(name="a.pdf", changes=None, rows=None):
    return {
        "file_name": name,
        "header": {"bank_name": "Demo Bank", "account_number_masked": "XXXXXXXX1234", "period_start": "2026-09-01", "period_end": "2026-09-30"},
        "transactions": rows if rows is not None else [{"date": "2026-09-02", "description": "UPI/SWIGGY", "withdrawal": "450.00"}],
        "changes": changes or [],
    }


def test_save_writes_audit_entries_and_does_not_store_changes(client):
    ch = [{"where": "Row 1", "field": "withdrawal", "old": "540.00", "new": "450.00"}]
    r = client.post("/api/statements", json=body(changes=ch))
    assert r.status_code == 201
    sid = r.json()["id"]
    assert r.json()["statement"]["changes"] == []
    assert client.get(f"/api/statements/{sid}").json()["statement"]["changes"] == []
    log = client.get("/api/audit", params={"statement_id": sid}).json()
    assert [e["action"] for e in log] == ["edited", "saved"]
    assert log[0]["old"] == "540.00" and log[0]["new"] == "450.00" and log[0]["where"] == "Row 1"
    assert "1 transactions" in log[1]["detail"]


def test_delete_is_logged(client):
    sid = client.post("/api/statements", json=body("gone.pdf")).json()["id"]
    assert client.delete(f"/api/statements/{sid}").status_code == 204
    entries = client.get("/api/audit", params={"statement_id": sid}).json()
    assert entries[0]["action"] == "deleted" and entries[0]["detail"] == "gone.pdf"
    assert client.delete(f"/api/statements/{sid}").status_code == 404
    assert len(client.get("/api/audit", params={"statement_id": sid}).json()) == 2  # failed delete adds nothing


def test_check_endpoint_warns_but_saves_nothing(client):
    sid = client.post("/api/statements", json=body()).json()["id"]
    w = client.post("/api/statements/check", json=body("again.pdf")).json()
    assert [x["kind"] for x in w] == ["duplicate"] and w[0]["statement_id"] == sid
    assert len(client.get("/api/statements").json()) == 1
    other = body("other.pdf", rows=[{"date": "2026-10-02", "description": "NEW", "withdrawal": "5.00"}])
    other["header"].update(period_start="2026-10-01", period_end="2026-10-31")
    assert client.post("/api/statements/check", json=other).json() == []


def test_saving_a_duplicate_is_still_allowed(client):
    assert client.post("/api/statements", json=body()).status_code == 201
    assert client.post("/api/statements", json=body()).status_code == 201


def test_audit_validation(client):
    bad = body(changes=[{"where": "x" * 41, "field": "f"}])
    assert client.post("/api/statements", json=bad).status_code == 422
