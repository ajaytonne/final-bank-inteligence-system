import pymupdf
import pytest

import statement_analyser as sa
from statement_analyser.services.bank_profiles import identify_bank
from statement_analyser.services.tamper_check import check_pdf


# ---- bank identification ---------------------------------------------------------------------------
@pytest.mark.parametrize("ifsc, name", [("HDFC0001234", "HDFC Bank"), ("sbin0000300", "State Bank of India"), ("UTIB0000001", "Axis Bank"),
                                        ("ICIC0000104", "ICICI Bank"), ("KKBK0000958", "Kotak Mahindra Bank")])
def test_bank_from_ifsc(ifsc, name):
    b = identify_bank(ifsc)
    assert b["name"] == name and b["source"] == "ifsc"


def test_ifsc_in_the_text_beats_the_wording():
    b = identify_bank(None, "Statement of account  IFSC: ICIC0000104  Powered by HDFC gateway")
    assert (b["name"], b["source"]) == ("ICICI Bank", "ifsc")


def test_a_narration_naming_another_bank_does_not_change_the_bank():
    text = ("DEMO BANK LTD  Account Statement\nAccount Holder: P\nDate  Narration  Withdrawal  Deposit  Balance\n"
            "02/09/2026  NEFT TRANSFER TO ICICI 5678 ICIC0000104 HDFC BANK  100.00")
    assert identify_bank(None, text) is None  # the title block names no real bank; the table rows are ignored
    assert identify_bank(None, "HDFC BANK Ltd\n" + text)["name"] == "HDFC Bank"


def test_bank_from_name_and_unknown():
    assert identify_bank(None, "PUNJAB NATIONAL BANK  Account statement")["name"] == "Punjab National Bank"
    assert identify_bank("ZZZZ0000001", "nothing useful") is None
    assert identify_bank("HDFC", "")["code"] == "HDFC"
    assert identify_bank("HDFCX000001", "") is None  # the fifth character of an IFSC is always 0


# ---- tamper checks ---------------------------------------------------------------------------------
def test_clean_generated_statement(text_pdf):
    t = check_pdf(text_pdf)
    assert t["status"] == "clean" and t["flags"] == []


def test_editor_and_annotation_are_flagged(text_pdf):
    doc = pymupdf.open(stream=text_pdf, filetype="pdf")
    doc.set_metadata({"producer": "iLovePDF", "creator": "Sejda"})
    doc[0].add_text_annot((50, 50), "changed")
    t = check_pdf(doc.tobytes())
    codes = {f["code"]: f["severity"] for f in t["flags"]}
    assert t["status"] == "suspicious" and codes["editor_software"] == "high" and codes["annotations"] == "high"


def test_incremental_save_is_flagged(tmp_path, text_pdf):
    p = tmp_path / "s.pdf"
    p.write_bytes(text_pdf)
    doc = pymupdf.open(str(p))
    doc[0].insert_text((50, 20), "patched")
    doc.save(str(p), incremental=True, encryption=pymupdf.PDF_ENCRYPT_KEEP)
    assert "incremental_save" in {f["code"] for f in check_pdf(p.read_bytes())["flags"]}


def test_tamper_check_never_crashes_on_bad_input():
    assert check_pdf(b"%PDF-1.4 broken")["status"] == "unavailable"


# ---- password protected PDFs -------------------------------------------------------------------------
@pytest.fixture
def locked(text_pdf):
    doc = pymupdf.open(stream=text_pdf, filetype="pdf")
    return doc.tobytes(encryption=pymupdf.PDF_ENCRYPT_AES_256, user_pw="secret", owner_pw="owner")


def test_locked_pdf_needs_the_right_password(locked):
    with pytest.raises(ValueError, match="password protected"):
        sa.analyse(locked, name="l.pdf")
    with pytest.raises(ValueError, match="wrong"):
        sa.analyse(locked, name="l.pdf", password="nope")
    assert len(sa.analyse(locked, name="l.pdf", password="secret").transactions) == 14


def test_full_analysis_of_a_locked_pdf(locked):
    out = sa.analyse_full(locked, name="l.pdf", password="secret")
    assert out["extraction"]["page_count"] >= 1 and out["tamper"]["status"] == "clean"


# ---- full analysis ---------------------------------------------------------------------------------
def test_analyse_full_shape(text_pdf):
    out = sa.analyse_full(text_pdf, name="s.pdf")
    assert set(out) == {"file_name", "bank", "extraction", "analytics", "tamper", "flags"}
    assert "raw_text" not in out["extraction"]  # the raw text is not part of the analysis output
    assert out["analytics"]["transaction_count"] == 14
    assert out["analytics"]["salary"]["detected"] is True
    levels = [f["level"] for f in out["flags"]]
    assert levels == sorted(levels, key={"high": 0, "medium": 1, "low": 2, "info": 3}.get)


def test_tampered_statement_is_flagged_by_the_balance_chain(tampered_pdf):
    out = sa.analyse_full(tampered_pdf, name="t.pdf")
    assert "balance_chain" in {f["code"] for f in out["flags"]} and out["flags"][0]["level"] == "high"


# ---- screens' endpoints ----------------------------------------------------------------------------
def test_analysis_endpoint(client, text_pdf):
    r = client.post("/api/analysis", files={"file": ("s.pdf", text_pdf, "application/pdf")})
    assert r.status_code == 200 and r.json()["analytics"]["transaction_count"] == 14


def test_analysis_endpoint_errors(client, locked):
    assert client.post("/api/analysis", files={"file": ("l.pdf", locked, "application/pdf")}).status_code == 422
    ok = client.post("/api/analysis", files={"file": ("l.pdf", locked, "application/pdf")}, data={"password": "secret"})
    assert ok.status_code == 200
    assert client.post("/api/analysis", files={"file": ("x.txt", b"hi", "text/plain")}).status_code == 415


def test_analytics_of_a_saved_statement(client):
    body = {"file_name": "a.pdf", "header": {"ifsc": "HDFC0001234", "period_start": "2026-07-01", "period_end": "2026-07-31"},
            "transactions": [{"date": "2026-07-01", "description": "SALARY ACME", "deposit": "40000.00", "balance": "40000.00"},
                             {"date": "2026-07-02", "description": "CHQ RETURN INSUFFICIENT FUNDS", "withdrawal": "300.00", "balance": "39700.00"}]}
    sid = client.post("/api/statements", json=body).json()["id"]
    out = client.get(f"/api/statements/{sid}/analytics").json()
    assert out["bank"]["name"] == "HDFC Bank" and out["tamper"] is None
    assert out["analytics"]["salary"]["detected"] and out["analytics"]["bounces"]["count"] == 1
    assert {f["code"] for f in out["flags"]} == {"bounces"}
    assert client.get("/api/statements/999/analytics").status_code == 404


def test_saved_statement_csv_export_includes_currency(client):
    body = {
        "file_name": "usd.pdf",
        "header": {"currency": "USD"},
        "review_metadata": {
            "extraction_method": "ocr", "average_confidence": 0.8, "field_count": 10,
            "ocr_field_count": 8, "pdf_text_field_count": 0, "derived_field_count": 2,
            "low_confidence_field_count": 2,
        },
        "transactions": [{"date": "2026-07-01", "description": "Coffee", "withdrawal": "4.50", "balance": "95.50"}],
    }
    sid = client.post("/api/statements", json=body).json()["id"]
    saved = client.get(f"/api/statements/{sid}").json()
    assert saved["statement"]["review_metadata"]["ocr_field_count"] == 8
    response = client.get(f"/api/statements/{sid}/export.csv")
    assert response.status_code == 200
    assert "Currency" in response.text and ",USD," in response.text
    assert f'filename="statement-{sid}.csv"' in response.headers["content-disposition"]
    assert client.get("/api/statements/999/export.csv").status_code == 404


# ---- asynchronous API v1 -----------------------------------------------------------------------------
def submit(client, pdf, **extra):
    return client.post("/api/v1/analyses", files={"file": ("s.pdf", pdf, "application/pdf")}, **extra)


def test_submit_then_fetch_the_result(client, text_pdf):
    r = submit(client, text_pdf)
    assert r.status_code == 202 and r.json()["status"] == "queued"
    job = client.get(r.json()["status_url"]).json()  # the background task has run by now
    assert job["status"] == "done" and job["error"] is None and job["finished_at"]
    assert job["result"]["analytics"]["transaction_count"] == 14
    assert [j["id"] for j in client.get("/api/v1/analyses").json()] == [job["id"]]
    assert "result" not in client.get("/api/v1/analyses").json()[0]  # the list stays light
    assert client.delete(f"/api/v1/analyses/{job['id']}").status_code == 204
    assert client.get(f"/api/v1/analyses/{job['id']}").status_code == 404
    assert client.delete(f"/api/v1/analyses/{job['id']}").status_code == 404


def test_a_failed_job_keeps_the_reason(client, text_pdf):
    doc = pymupdf.open(stream=text_pdf, filetype="pdf")
    locked = doc.tobytes(encryption=pymupdf.PDF_ENCRYPT_AES_256, user_pw="secret", owner_pw="o")
    job = client.get(submit(client, locked).json()["status_url"]).json()
    assert job["status"] == "failed" and "password" in job["error"] and job["result"] is None
    ok = client.get(submit(client, locked, data={"password": "secret"}).json()["status_url"]).json()
    assert ok["status"] == "done"


def test_bad_uploads_are_refused_at_submit(client):
    assert client.post("/api/v1/analyses", files={"file": ("x.pdf", b"not a pdf", "application/pdf")}).status_code == 415
    assert client.get("/api/v1/analyses/doesnotexist").status_code == 404


# ---- API keys ----------------------------------------------------------------------------------------
@pytest.fixture
def keyed(settings, client):
    from dataclasses import replace
    from statement_analyser.main import app, settings_dep

    app.dependency_overrides[settings_dep] = lambda: replace(settings, api_keys=["k-123", "k-456"])
    return client


def test_api_key_is_required_when_configured(keyed, text_pdf):
    assert submit(keyed, text_pdf).status_code == 401
    assert submit(keyed, text_pdf, headers={"X-API-Key": "wrong"}).status_code == 401
    ok = submit(keyed, text_pdf, headers={"X-API-Key": "k-456"})
    assert ok.status_code == 202
    assert keyed.get(ok.json()["status_url"]).status_code == 401
    assert keyed.get(ok.json()["status_url"], headers={"X-API-Key": "k-456"}).json()["status"] == "done"
    assert keyed.get("/api/v1/analyses").status_code == 401 and keyed.delete("/api/v1/analyses/x").status_code == 401


def test_screens_do_not_need_a_key(keyed, text_pdf):
    assert keyed.post("/api/analysis", files={"file": ("s.pdf", text_pdf, "application/pdf")}).status_code == 200


# ---- webhook -----------------------------------------------------------------------------------------
@pytest.fixture
def hooks(settings, client):
    from dataclasses import replace
    from statement_analyser.main import app, settings_dep

    app.dependency_overrides[settings_dep] = lambda: replace(settings, webhook_allowed_hosts=["hooks.example.com"])
    return client


@pytest.mark.parametrize("url", ["http://hooks.example.com/x", "https://evil.example.org/x", "https://169.254.169.254/latest", "ftp://hooks.example.com"])
def test_callback_must_be_https_and_allowed(hooks, text_pdf, url):
    assert submit(hooks, text_pdf, data={"callback_url": url}).status_code == 422


def test_callback_off_by_default(client, text_pdf):
    assert submit(client, text_pdf, data={"callback_url": "https://hooks.example.com/x"}).status_code == 422


def test_webhook_is_posted_once_the_job_finishes(hooks, text_pdf, monkeypatch):
    sent = {}

    class Resp:
        status_code = 200

    def fake_post(url, json, timeout, follow_redirects):
        sent.update(url=url, body=json, follow=follow_redirects)
        return Resp()

    monkeypatch.setattr("statement_analyser.routes_analysis.httpx.post", fake_post)
    r = submit(hooks, text_pdf, data={"callback_url": "https://hooks.example.com/done"})
    job = hooks.get(r.json()["status_url"]).json()
    assert sent["url"] == "https://hooks.example.com/done" and sent["follow"] is False
    assert sent["body"]["id"] == job["id"] and sent["body"]["status"] == "done" and sent["body"]["result"]["analytics"]
    assert job["webhook_status"] == "delivered (200)"


def test_a_failing_webhook_does_not_lose_the_result(hooks, text_pdf, monkeypatch):
    def boom(*a, **k):
        raise ConnectionError("down")

    monkeypatch.setattr("statement_analyser.routes_analysis.httpx.post", boom)
    job = hooks.get(submit(hooks, text_pdf, data={"callback_url": "https://hooks.example.com/x"}).json()["status_url"]).json()
    assert job["status"] == "done" and job["webhook_status"] == "failed (ConnectionError)"
