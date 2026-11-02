from dataclasses import replace
from datetime import date
from decimal import Decimal

import httpx

from app.config import Settings
from app.services import llm
from app.services.parser import FieldGuess

TEXT = "Customer: Rahul Verma  A/C 9876543210  From 01/08/2026 to 31/08/2026 Opening 5,000.00"


def empty_header():
    keys = ["account_holder", "account_number_masked", "period_start", "period_end", "opening_balance", "closing_balance"]
    return {k: FieldGuess() for k in keys}


def on():
    return replace(Settings(), ollama_enabled=True)


def test_disabled_does_nothing(monkeypatch):
    called = []
    monkeypatch.setattr(llm, "ask_ollama", lambda *a: called.append(1))
    used, warns = llm.fill_missing_header(empty_header(), TEXT, replace(Settings(), ollama_enabled=False))
    assert used is False and not called and warns == []


def test_fills_only_grounded_fields(monkeypatch):
    monkeypatch.setattr(
        llm,
        "ask_ollama",
        lambda *a: {
            "account_holder": "Rahul Verma",
            "account_number": "9876543210",
            "period_start": "01/08/2026",
            "period_end": "31/08/2026",
            "opening_balance": "5,000.00",
            "closing_balance": "7,777.00",  # not in text
        },
    )
    h = empty_header()
    used, _ = llm.fill_missing_header(h, TEXT, on())
    assert used
    assert h["account_holder"].value == "Rahul Verma"
    assert h["account_holder"].source == "llm"
    assert h["account_number_masked"].value == "XXXXXX3210"
    assert h["period_start"].value == date(2026, 8, 1)
    assert h["opening_balance"].value == Decimal("5000.00")
    assert h["closing_balance"].value is None  # rejected


def test_does_not_overwrite_existing(monkeypatch):
    monkeypatch.setattr(llm, "ask_ollama", lambda *a: {"account_holder": "Rahul Verma"})
    h = empty_header()
    h["account_holder"] = FieldGuess("Priya", 0.95, "pdf_text")
    llm.fill_missing_header(h, TEXT, on())
    assert h["account_holder"].value == "Priya"


def test_unavailable_adds_warning(monkeypatch):
    monkeypatch.setattr(llm, "ask_ollama", lambda *a: None)
    used, warns = llm.fill_missing_header(empty_header(), TEXT, on())
    assert used is False and "unavailable" in warns[0]


def test_ask_ollama_handles_connection_error(monkeypatch):
    def boom(*a, **k):
        raise httpx.ConnectError("down")

    monkeypatch.setattr(httpx, "post", boom)
    assert llm.ask_ollama("x", on()) is None


def test_ask_ollama_parses_json(monkeypatch):
    class Resp:
        status_code = 200

        def raise_for_status(self):
            pass

        def json(self):
            return {"response": '{"account_holder": "A"}'}

    monkeypatch.setattr(httpx, "post", lambda *a, **k: Resp())
    assert llm.ask_ollama("x", on()) == {"account_holder": "A"}


def test_ask_ollama_bad_json(monkeypatch):
    class Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"response": "not json"}

    monkeypatch.setattr(httpx, "post", lambda *a, **k: Resp())
    assert llm.ask_ollama("x", on()) is None


def test_grounded():
    assert llm.grounded("5,000.00", "balance 5000.00")
    assert not llm.grounded("Someone Else", TEXT)
