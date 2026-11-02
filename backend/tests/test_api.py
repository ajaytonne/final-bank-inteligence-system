def upload(client, name, data, ctype="application/pdf"):
    return client.post("/api/extract", files={"file": (name, data, ctype)})


def reviewed(**over):
    body = {
        "file_name": "s.pdf",
        "header": {
            "account_holder": "Priya Sharma",
            "account_number_masked": "XXXXXXXX1234",
            "period_start": "2026-09-01",
            "period_end": "2026-09-30",
            "opening_balance": "25000.00",
            "closing_balance": "24900.00",
        },
        "transactions": [
            {"date": "2026-09-02", "description": "ATM", "reference": "TXN1", "withdrawal": "100.00", "balance": "24900.00"}
        ],
    }
    body.update(over)
    return body


def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"
    assert r.json()["ollama_enabled"] is False


def test_extract_text_pdf(client, text_pdf):
    r = upload(client, "statement.pdf", text_pdf)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["file_name"] == "statement.pdf"
    assert body["header"]["account_holder"]["value"] == "Priya Sharma"
    assert body["header"]["opening_balance"]["value"] == "25000.00"  # decimal as string
    assert body["validation"]["status"] == "passed"
    assert "heuristic" in body["confidence_note"]
    t = body["transactions"][0]
    assert set(t) >= {"date", "description", "reference", "deposit", "withdrawal", "balance", "confidence", "needs_review"}


def test_extract_rejects_bad_type(client):
    r = upload(client, "x.txt", b"hello", "text/plain")
    assert r.status_code == 415


def test_extract_rejects_spoofed_pdf(client):
    r = upload(client, "x.pdf", b"\x89PNG\r\n\x1a\nxxxx", "application/pdf")
    assert r.status_code == 415


def test_extract_rejects_large(client, settings):
    r = upload(client, "x.pdf", b"%PDF-" + b"0" * (settings.max_upload_bytes + 10))
    assert r.status_code == 413


def test_extract_broken_pdf_422(client):
    r = upload(client, "x.pdf", b"%PDF-1.4 garbage")
    assert r.status_code == 422


def test_extract_ocr_unavailable_503(client, png_statement, monkeypatch):
    from app.services import text_extraction

    monkeypatch.setattr(text_extraction, "tesseract_available", lambda: False)
    monkeypatch.setattr(text_extraction, "rapidocr_available", lambda: False)
    r = upload(client, "x.png", png_statement, "image/png")
    assert r.status_code == 503


def test_save_list_get_delete(client):
    r = client.post("/api/statements", json=reviewed())
    assert r.status_code == 201, r.text
    sid = r.json()["id"]
    lst = client.get("/api/statements").json()
    assert lst[0]["id"] == sid and lst[0]["transaction_count"] == 1
    got = client.get(f"/api/statements/{sid}").json()
    assert got["statement"]["header"]["account_holder"] == "Priya Sharma"
    assert client.delete(f"/api/statements/{sid}").status_code == 204
    assert client.get(f"/api/statements/{sid}").status_code == 404
    assert client.delete(f"/api/statements/{sid}").status_code == 404


def test_save_rejects_unmasked_account(client):
    body = reviewed()
    body["header"]["account_number_masked"] = "123456781234"
    assert client.post("/api/statements", json=body).status_code == 422


def test_save_rejects_both_sides(client):
    body = reviewed(transactions=[{"date": "2026-09-02", "deposit": "1.00", "withdrawal": "1.00"}])
    assert client.post("/api/statements", json=body).status_code == 422


def test_save_rejects_negative_amount(client):
    body = reviewed(transactions=[{"date": "2026-09-02", "deposit": "-5.00"}])
    assert client.post("/api/statements", json=body).status_code == 422


def test_save_rejects_period_order(client):
    body = reviewed()
    body["header"]["period_start"] = "2026-10-01"
    assert client.post("/api/statements", json=body).status_code == 422


def test_full_flow_extract_then_save(client, text_pdf):
    ex = upload(client, "statement.pdf", text_pdf).json()
    payload = {
        "file_name": ex["file_name"],
        "header": {k: v["value"] for k, v in ex["header"].items()},
        "transactions": [
            {k: t[k]["value"] for k in ("date", "description", "reference", "deposit", "withdrawal", "balance")}
            for t in ex["transactions"]
        ],
    }
    r = client.post("/api/statements", json=payload)
    assert r.status_code == 201, r.text
    assert len(r.json()["statement"]["transactions"]) == len(ex["transactions"])
