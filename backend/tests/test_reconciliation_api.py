import pytest


def stmt(client, name, bank, last4, txns, start="2026-09-01", end="2026-09-30"):
    body = {
        "file_name": name,
        "header": {"bank_name": bank, "account_number_masked": f"XXXX{last4}", "period_start": start, "period_end": end},
        "transactions": [
            {"date": d, "description": desc, "reference": ref, ("withdrawal" if kind == "debit" else "deposit"): amt}
            for d, desc, ref, amt, kind in txns
        ],
    }
    r = client.post("/api/statements", json=body)
    assert r.status_code == 201, r.text
    return r.json()["id"]


@pytest.fixture
def banks(client):
    """An SBI statement and an HDFC statement with one real transfer, one lookalike and one unrelated row each."""
    sbi = stmt(client, "sbi.pdf", "SBI", "1111", [
        ("2026-09-05", "NEFT TO HDFC SELF", "UTR1", "10000.00", "debit"),
        ("2026-09-06", "RENT", "", "777.00", "debit"),
        ("2026-09-07", "UPI/SWIGGY/1", "R3", "350.00", "debit"),
    ])
    hdfc = stmt(client, "hdfc.pdf", "HDFC", "2222", [
        ("2026-09-06", "NEFT FROM SBI SELF", "UTR1", "10000.00", "credit"),
        ("2026-09-06", "SALARY ACME", "", "777.00", "credit"),
        ("2026-09-09", "BONUS", "", "5000.00", "credit"),
    ])
    return sbi, hdfc


def run(client, kind, a, b, window=None):
    body = {"kind": kind, "statement_a_id": a, "statement_b_id": b}
    if window is not None:
        body["date_window_days"] = window
    r = client.post("/api/reconciliations", json=body)
    assert r.status_code == 201, r.text
    d = client.post(f"/api/reconciliations/{r.json()['id']}/run")
    assert d.status_code == 200, d.text
    return d.json()


def row(detail, status):
    return [m for m in detail["matches"] if m["status"] == status]


# ---- bank accounts ---------------------------------------------------------------------------
def test_bank_accounts_and_assignment(client, banks):
    sbi, _ = banks
    a = client.post("/api/bank-accounts", json={"bank_name": "SBI", "account_label": "SBI Savings", "account_number_masked": "XXXX1111"})
    assert a.status_code == 201 and a.json()["ownership_confirmed"] is False
    aid = a.json()["id"]
    assert client.put(f"/api/bank-accounts/{aid}", json={"ownership_confirmed": True}).json()["ownership_confirmed"] is True
    assert client.get("/api/bank-accounts").json()[0]["account_label"] == "SBI Savings"
    assert client.put(f"/api/statements/{sbi}/account", json={"account_id": aid}).json() == {"statement_id": sbi, "account_id": aid}
    assert client.get("/api/statement-accounts").json() == [{"statement_id": sbi, "account_id": aid}]
    assert client.put(f"/api/statements/{sbi}/account", json={"account_id": None}).status_code == 200
    assert client.get("/api/statement-accounts").json() == []


def test_bank_account_validation(client, banks):
    assert client.post("/api/bank-accounts", json={"bank_name": "SBI", "account_label": "x", "account_number_masked": "123456781234"}).status_code == 422
    assert client.post("/api/bank-accounts", json={"bank_name": "", "account_label": "x"}).status_code == 422
    assert client.put("/api/bank-accounts/99", json={"ownership_confirmed": True}).status_code == 404
    assert client.put("/api/statements/999/account", json={"account_id": None}).status_code == 404
    assert client.put(f"/api/statements/{banks[0]}/account", json={"account_id": 99}).status_code == 404


# ---- creating and running ----------------------------------------------------------------------
def test_inter_bank_flow_and_summary(client, banks):
    d = run(client, "inter_bank", *banks)
    assert d["session"]["status"] == "completed" and d["session"]["date_window_days"] == 2
    matched = row(d, "Matched") + row(d, "Timing Difference")
    assert len(matched) == 1 and matched[0]["match_type"] == "Reference" and matched[0]["a"]["amount"] == "10000.00"
    assert matched[0]["a"]["direction"] == "debit" and matched[0]["b"]["direction"] == "credit"
    possible = row(d, "Possible Match")  # same amount 777 but unrelated narrations: only a suggestion
    assert len(possible) == 1 and possible[0]["confirmation_status"] == "pending" and possible[0]["match_type"] == "Amount only"
    s = d["summary"]
    assert (s["total_a"], s["total_b"], s["possible_matches"], s["unmatched"]) == (3, 3, 1, 2)
    assert (float(s["total_matched_amount"]), float(s["total_unmatched_amount"])) == (10000.0, 5350.0)


def test_create_validation(client, banks):
    sbi, hdfc = banks
    post = lambda **kw: client.post("/api/reconciliations", json={"kind": "inter_bank", "statement_a_id": sbi, "statement_b_id": hdfc, **kw})
    assert post(statement_b_id=sbi).status_code == 422  # same statement twice
    assert post(statement_b_id=999).status_code == 404
    assert post(date_window_days=8).status_code == 422
    assert post(kind="other").status_code == 422
    assert client.post("/api/reconciliations", json={"kind": "internal", "statement_a_id": sbi, "statement_b_id": hdfc}).status_code == 422  # different banks
    twin = stmt(client, "sbi2.pdf", "SBI", "1111", [])
    assert client.post("/api/reconciliations", json={"kind": "inter_bank", "statement_a_id": sbi, "statement_b_id": twin}).status_code == 422  # same account
    ok = client.post("/api/reconciliations", json={"kind": "internal", "statement_a_id": sbi, "statement_b_id": twin})
    assert ok.status_code == 201 and ok.json()["date_window_days"] == 0 and ok.json()["status"] == "created"


def test_run_twice_is_refused_and_unknown_session_404(client, banks):
    d = run(client, "inter_bank", *banks)
    sid = d["session"]["id"]
    assert client.post(f"/api/reconciliations/{sid}/run").status_code == 409
    assert client.get("/api/reconciliations/999").status_code == 404
    assert client.post("/api/reconciliations/999/run").status_code == 404


def test_internal_reconciliation_duplicate_upload_and_missing(client):
    rows = [("2026-09-03", "SALARY", "T1", "50000.00", "credit"), ("2026-09-05", "RENT", "T2", "15000.00", "debit")]
    a = stmt(client, "a.pdf", "SBI", "1111", rows)
    b = stmt(client, "b.pdf", "SBI", "1111", rows)  # the same statement uploaded twice
    d = run(client, "internal", a, b)
    assert len(row(d, "Matched")) == 2 and any("second upload" in n for n in d["session"]["notes"])
    c = stmt(client, "c.pdf", "SBI", "1111", rows + [("2026-09-20", "ATM", "T9", "500.00", "debit")])
    d2 = run(client, "internal", c, a)
    assert len(row(d2, "Missing Transaction")) == 1 and d2["summary"]["missing_transactions"] == 1


def test_different_periods_are_labelled_not_reported_as_errors(client):
    a = stmt(client, "sep.pdf", "SBI", "1111", [("2026-09-05", "RENT", "T1", "100.00", "debit")])
    b = stmt(client, "nov.pdf", "SBI", "1111", [("2026-11-05", "RENT", "T1", "100.00", "debit")], start="2026-11-01", end="2026-11-30")
    d = run(client, "internal", a, b)
    s = d["summary"]
    assert (s["unmatched"], s["missing_transactions"], s["period_gaps"]) == (0, 0, 2) and "do not overlap" in d["session"]["notes"][0]


# ---- confirm / reject --------------------------------------------------------------------------
def test_confirm_a_possible_match(client, banks):
    d = run(client, "inter_bank", *banks)
    sid, m = d["session"]["id"], row(d, "Possible Match")[0]
    r = client.post(f"/api/reconciliations/{sid}/matches/{m['id']}/confirm", json={"note": "same payment"})
    assert r.status_code == 200
    done = next(x for x in r.json()["matches"] if x["id"] == m["id"])
    assert (done["status"], done["confirmation_status"], done["note"]) == ("Matched", "confirmed", "same payment")
    assert r.json()["summary"]["matched"] == 1 and r.json()["summary"]["possible_matches"] == 0


def test_reject_makes_the_transactions_unmatched(client, banks):
    d = run(client, "inter_bank", *banks)
    sid, m = d["session"]["id"], row(d, "Possible Match")[0]
    r = client.post(f"/api/reconciliations/{sid}/matches/{m['id']}/reject").json()
    assert next(x for x in r["matches"] if x["id"] == m["id"])["status"] == "Rejected Match"
    assert r["summary"]["rejected"] == 1 and r["summary"]["possible_matches"] == 0
    assert r["summary"]["unmatched"] == d["summary"]["unmatched"] + 2  # both transactions are reported as unmatched again


def test_one_transaction_cannot_be_in_two_confirmed_pairs(client):
    a = stmt(client, "a.pdf", "SBI", "1111", [("2026-09-05", "TRANSFER", "", "500.00", "debit")])
    b = stmt(client, "b.pdf", "HDFC", "2222", [("2026-09-05", "TRANSFER", "", "500.00", "credit"), ("2026-09-05", "TRANSFER", "", "500.00", "credit")])
    d = run(client, "inter_bank", a, b)
    manual = row(d, "Manual Review")
    assert len(manual) == 2 and not row(d, "Matched")  # identical evidence: nothing was chosen automatically
    sid = d["session"]["id"]
    assert client.post(f"/api/reconciliations/{sid}/matches/{manual[0]['id']}/confirm").status_code == 200
    again = client.post(f"/api/reconciliations/{sid}/matches/{manual[1]['id']}/confirm")
    assert again.status_code == 409 and "already belongs to another matched pair" in again.json()["detail"]
    assert client.post(f"/api/reconciliations/{sid}/matches/{manual[0]['id']}/reject").status_code == 200  # reject the first ...
    assert client.post(f"/api/reconciliations/{sid}/matches/{manual[1]['id']}/confirm").status_code == 200  # ... now the other can be chosen


def test_only_pairs_can_be_decided(client, banks):
    d = run(client, "inter_bank", *banks)
    sid, lone = d["session"]["id"], row(d, "Unmatched")[0]
    assert client.post(f"/api/reconciliations/{sid}/matches/{lone['id']}/confirm").status_code == 422
    assert client.post(f"/api/reconciliations/{sid}/matches/9999/reject").status_code == 404


def test_duplicate_candidates_are_shown_and_never_deleted(client):
    t = ("2026-09-04", "UPI/SWIGGY/1", "R1", "350.00", "debit")
    a = stmt(client, "a.pdf", "SBI", "1111", [t, t])
    b = stmt(client, "b.pdf", "SBI", "1111", [])
    d = run(client, "internal", a, b)
    dup = row(d, "Duplicate Candidate")
    assert len(dup) == 1 and dup[0]["confirmation_status"] == "pending"
    r = client.post(f"/api/reconciliations/{d['session']['id']}/matches/{dup[0]['id']}/confirm").json()
    assert next(x for x in r["matches"] if x["id"] == dup[0]["id"])["status"] == "Duplicate Candidate"  # confirmed, still listed
    assert len(client.get(f"/api/statements/{a}").json()["statement"]["transactions"]) == 2  # nothing removed


# ---- internal transfers and consolidated totals -------------------------------------------------
def test_confirmed_internal_transfers_leave_consolidated_totals(client, banks):
    sbi, hdfc = banks
    for sid, label, num in ((sbi, "SBI", "XXXX1111"), (hdfc, "HDFC", "XXXX2222")):
        acc = client.post("/api/bank-accounts", json={"bank_name": label, "account_label": label, "account_number_masked": num, "ownership_confirmed": True}).json()
        client.put(f"/api/statements/{sid}/account", json={"account_id": acc["id"]})
    d = run(client, "inter_bank", sbi, hdfc)
    sid = d["session"]["id"]
    pair = (row(d, "Matched") + row(d, "Timing Difference"))[0]
    assert pair["internal_transfer"] is True  # both accounts are confirmed as the user's
    assert not any(m["internal_transfer"] for m in row(d, "Possible Match"))  # amount alone is never a transfer
    before = client.get(f"/api/reconciliations/{sid}/consolidated").json()
    assert (float(before["income"]), float(before["expenses"]), before["excluded_transfer_count"]) == (15777.0, 11127.0, 0)  # not confirmed: nothing excluded
    after_confirm = client.post(f"/api/reconciliations/{sid}/matches/{pair['id']}/confirm").json()
    assert after_confirm["summary"]["confirmed_internal_transfers"] == 1
    after = client.get(f"/api/reconciliations/{sid}/consolidated").json()
    assert (float(after["income"]), float(after["expenses"]), float(after["savings"])) == (5777.0, 1127.0, 4650.0)
    assert (after["excluded_transfer_count"], float(after["excluded_amount"])) == (1, 10000.0)


def test_unknown_accounts_are_not_called_internal_transfers(client, banks):
    d = run(client, "inter_bank", *banks)  # no account ownership confirmed
    assert not any(m["internal_transfer"] for m in d["matches"])


# ---- export, delete, originals ----------------------------------------------------------------
def test_export_csv(client):
    a = stmt(client, "a.pdf", "SBI", "1111", [("2026-09-05", "=HYPERLINK(1)", "U1", "100.00", "debit")])
    b = stmt(client, "b.pdf", "HDFC", "2222", [("2026-09-05", "=HYPERLINK(1)", "U1", "100.00", "credit")])
    d = run(client, "inter_bank", a, b)
    r = client.get(f"/api/reconciliations/{d['session']['id']}/export")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    assert "reconciliation-" in r.headers["content-disposition"]
    text = r.content.decode("utf-8-sig").splitlines()
    assert text[0].startswith("Status,Match type,Confidence")
    assert len(text) == 2 and text[1].startswith("Matched,Reference,")
    assert "'=HYPERLINK(1)" in text[1] and ",=HYPERLINK" not in text[1]  # cannot run as a spreadsheet formula
    assert client.get("/api/reconciliations/999/export").status_code == 404


def test_delete_session_keeps_statements(client, banks):
    d = run(client, "inter_bank", *banks)
    sid = d["session"]["id"]
    assert client.delete(f"/api/reconciliations/{sid}").status_code == 204
    assert client.get(f"/api/reconciliations/{sid}").status_code == 404
    assert client.delete(f"/api/reconciliations/{sid}").status_code == 404
    assert client.get(f"/api/statements/{banks[0]}").status_code == 200


def test_reconciliation_never_changes_the_original_transactions(client, banks):
    before = [client.get(f"/api/statements/{s}").json() for s in banks]
    d = run(client, "inter_bank", *banks)
    sid = d["session"]["id"]
    for m in d["matches"]:
        if m["a_index"] is not None and m["b_index"] is not None:
            client.post(f"/api/reconciliations/{sid}/matches/{m['id']}/confirm")
    client.post(f"/api/reconciliations/{sid}/matches/{row(d, 'Possible Match')[0]['id']}/reject")
    client.get(f"/api/reconciliations/{sid}/consolidated")
    assert [client.get(f"/api/statements/{s}").json() for s in banks] == before
    assert len(client.get("/api/statements").json()) == 2


def test_no_uncertain_match_is_confirmed_automatically(client, banks):
    d = run(client, "inter_bank", *banks)
    for m in d["matches"]:
        if m["status"] in ("Possible Match", "Manual Review", "Duplicate Candidate"):
            assert m["confirmation_status"] == "pending"
        assert m["confirmation_status"] != "confirmed"  # nothing is confirmed until a person does it
