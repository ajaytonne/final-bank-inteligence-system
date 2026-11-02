from datetime import date
from decimal import Decimal

import pytest

from app.services.file_validation import validate_upload
from app.services.pipeline import run_extraction
from app.services.text_extraction import tesseract_available

needs_ocr = pytest.mark.skipif(not tesseract_available(), reason="tesseract not installed")


def run(name, data, settings):
    return run_extraction(validate_upload(name, data, settings.max_upload_bytes), settings)


def test_text_pdf_full_extraction(text_pdf, txns, expected_closing, settings):
    r = run("s.pdf", text_pdf, settings)
    assert r.method == "pdf_text" and r.page_count == 2
    assert r.header.account_holder.value == "Priya Sharma"
    assert r.header.account_number_masked.value == "XXXXXXXX1234"
    assert r.header.period_start.value == date(2026, 9, 1)
    assert r.header.opening_balance.value == Decimal("25000.00")
    assert r.header.closing_balance.value == expected_closing
    assert len(r.transactions) == len(txns)
    for t, src in zip(r.transactions, txns):
        assert t.date.value == src.day
        assert t.reference.value == src.ref
        assert t.withdrawal.value == src.withdrawal
        assert t.deposit.value == src.deposit
    assert r.validation.status == "passed"
    assert r.review_required_count == 0
    assert "MONTHLY PAYMENT" in r.transactions[2].description.value


def test_tampered_pdf_flags_rows(tampered_pdf, settings):
    r = run("t.pdf", tampered_pdf, settings)
    assert r.validation.status == "failed"
    assert 5 in r.validation.mismatched_rows
    assert r.transactions[5].needs_review
    assert r.review_required_count >= 1


def test_full_account_number_is_masked(full_account_pdf, settings):
    r = run("f.pdf", full_account_pdf, settings)
    assert r.header.account_number_masked.value == "XXXXXXXX1234"
    assert "123456781234" not in r.model_dump_json()  # raw text redacted
    assert "masked" in (r.header.account_number_masked.note or "")


def test_positional_fallback(no_header_pdf, txns, settings):
    r = run("n.pdf", no_header_pdf, settings)
    assert len(r.transactions) == len(txns)
    assert r.validation.status == "passed"
    assert any("without a recognised table header" in w for w in r.warnings)
    assert all(t.withdrawal.value == s.withdrawal for t, s in zip(r.transactions, txns))


def test_missing_fields_flagged(settings):
    from reportlab.pdfgen import canvas
    import io

    buf = io.BytesIO()
    c = canvas.Canvas(buf)
    c.drawString(40, 800, "Some random document text that is long enough to count as text.")
    c.save()
    r = run("x.pdf", buf.getvalue(), settings)
    assert r.transactions == []
    assert r.header.account_holder.value is None
    assert r.header.account_holder.needs_review
    assert r.validation.status == "unavailable"
    assert any("No transaction rows" in w for w in r.warnings)


def test_bad_pdf_raises(settings):
    with pytest.raises(ValueError):
        run("x.pdf", b"%PDF-1.4 broken", settings)


@needs_ocr
def test_scanned_pdf_uses_ocr(scanned, txns, settings):
    r = run("scan.pdf", scanned, settings)
    assert r.method == "ocr" and r.ocr_pages == [1, 2]
    assert r.header.account_holder.value == "Priya Sharma"
    assert len(r.transactions) == len(txns)
    assert r.validation.status == "passed"
    assert all(0 < t.confidence <= 0.99 for t in r.transactions)


@needs_ocr
def test_png_image(png_statement, settings):
    r = run("scan.png", png_statement, settings)
    assert r.file_type == "image" and r.method == "ocr"
    assert len(r.transactions) == 6
    assert r.validation.status == "passed"
