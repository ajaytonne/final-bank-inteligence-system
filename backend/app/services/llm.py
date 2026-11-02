import json
import logging
import re
from typing import Optional

import httpx

from app.config import Settings
from app.services.normalize import clean_text, mask_account_number, parse_amount, parse_date
from app.services.parser import FieldGuess

log = logging.getLogger(__name__)

LLM_CONFIDENCE = 0.55
HEADER_KEYS = (
    "account_holder",
    "account_number",
    "period_start",
    "period_end",
    "opening_balance",
    "closing_balance",
)

PROMPT = """You extract fields from a bank statement. Use ONLY text that appears below.
If a field is not clearly present, return null. Never guess or calculate values.
Return JSON with exactly these keys:
account_holder, account_number, period_start, period_end, opening_balance, closing_balance.
Dates and amounts must be copied as they appear in the text.

STATEMENT TEXT:
<<<
{text}
>>>"""


def ollama_reachable(settings: Settings) -> bool:
    if not settings.ollama_enabled:
        return False
    try:
        r = httpx.get(f"{settings.ollama_url}/api/tags", timeout=3)
        return r.status_code == 200
    except httpx.HTTPError:
        return False


def _norm(s: str) -> str:
    return re.sub(r"[\s,]", "", s).lower()


def grounded(value: str, source_text: str) -> bool:
    return bool(value) and _norm(value) in _norm(source_text)


def ask_ollama(text: str, settings: Settings) -> Optional[dict]:
    payload = {
        "model": settings.ollama_model,
        "prompt": PROMPT.format(text=text[:4000]),
        "format": "json",
        "stream": False,
        "options": {"temperature": 0},
    }
    try:
        r = httpx.post(
            f"{settings.ollama_url}/api/generate", json=payload, timeout=settings.ollama_timeout
        )
        r.raise_for_status()
        data = json.loads(r.json().get("response", "{}"))
        return data if isinstance(data, dict) else None
    except (httpx.HTTPError, json.JSONDecodeError, ValueError) as exc:
        log.warning("Ollama call failed: %s", exc)
        return None


def fill_missing_header(
    header: dict[str, FieldGuess], text: str, settings: Settings
) -> tuple[bool, list[str]]:
    """Fill only missing header fields with grounded LLM values."""
    warnings: list[str] = []
    supported = {"account_holder", "account_number_masked", "period_start", "period_end", "opening_balance", "closing_balance"}
    missing = [k for k, f in header.items() if k in supported and f.value is None]
    if not settings.ollama_enabled or not missing or not text.strip():
        return False, warnings

    data = ask_ollama(text, settings)
    if data is None:
        warnings.append("Local LLM was enabled but unavailable; rule-based extraction only.")
        return False, warnings

    used = False
    note = "Suggested by local LLM; verify against the document"
    dayfirst = settings.date_dayfirst
    for key in missing:
        src_key = "account_number" if key == "account_number_masked" else key
        raw = data.get(src_key)
        if raw is None or not isinstance(raw, (str, int, float)):
            continue
        raw = str(raw).strip()
        if not grounded(raw, text):
            continue  # reject ungrounded
        value = None
        if key == "account_holder":
            value = clean_text(raw)
        elif key == "account_number_masked":
            value = mask_account_number(raw)
        elif key in ("period_start", "period_end"):
            value = parse_date(raw, dayfirst)
        else:
            value = parse_amount(raw)
        if value is not None:
            header[key] = FieldGuess(value, LLM_CONFIDENCE, "llm", note)
            used = True
    return used, warnings
