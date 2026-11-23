"""Bank identification. Every Indian bank branch has an IFSC code whose first four letters name the bank,
so the bank can be recognised even when the statement layout is unknown.

This only NAMES the bank. Reading each bank's own layout still depends on the generic parser; per-bank layout tuning needs real
(masked) statements from that bank. Add a bank by adding one line to IFSC_BANKS."""
import re
from typing import Optional

IFSC_BANKS = {
    "SBIN": "State Bank of India", "HDFC": "HDFC Bank", "ICIC": "ICICI Bank", "UTIB": "Axis Bank",
    "KKBK": "Kotak Mahindra Bank", "PUNB": "Punjab National Bank", "BARB": "Bank of Baroda",
    "CNRB": "Canara Bank", "UBIN": "Union Bank of India", "BKID": "Bank of India",
    "IDIB": "Indian Bank", "IOBA": "Indian Overseas Bank", "MAHB": "Bank of Maharashtra",
    "CBIN": "Central Bank of India", "UCBA": "UCO Bank", "PSIB": "Punjab & Sind Bank",
    "YESB": "Yes Bank", "IDFB": "IDFC First Bank", "INDB": "IndusInd Bank", "FDRL": "Federal Bank",
    "KARB": "Karnataka Bank", "SIBL": "South Indian Bank", "RATN": "RBL Bank", "AUBL": "AU Small Finance Bank",
    "BDBL": "Bandhan Bank", "CIUB": "City Union Bank", "KVBL": "Karur Vysya Bank", "TMBL": "Tamilnad Mercantile Bank",
    "DLXB": "Dhanlaxmi Bank", "JAKA": "Jammu & Kashmir Bank", "CSBK": "CSB Bank", "DCBL": "DCB Bank",
    "ESFB": "Equitas Small Finance Bank", "UJVN": "Ujjivan Small Finance Bank", "PYTM": "Paytm Payments Bank",
    "AIRP": "Airtel Payments Bank", "IPOS": "India Post Payments Bank", "HSBC": "HSBC", "SCBL": "Standard Chartered Bank",
    "CITI": "Citibank", "DBSS": "DBS Bank India", "NSPB": "NSDL Payments Bank", "FINO": "Fino Payments Bank",
}

_NAME_HINTS = [(re.compile(p, re.I), name) for p, name in [
    (r"\bstate bank of india\b|\bsbi\b", "State Bank of India"), (r"\bhdfc\b", "HDFC Bank"), (r"\bicici\b", "ICICI Bank"),
    (r"\baxis bank\b", "Axis Bank"), (r"\bkotak\b", "Kotak Mahindra Bank"), (r"\bpunjab national\b|\bpnb\b", "Punjab National Bank"),
    (r"\bbank of baroda\b", "Bank of Baroda"), (r"\bcanara\b", "Canara Bank"), (r"\bunion bank\b", "Union Bank of India"),
    (r"\byes bank\b", "Yes Bank"), (r"\bidfc\b", "IDFC First Bank"), (r"\bindusind\b", "IndusInd Bank"),
    (r"\bfederal bank\b", "Federal Bank"), (r"\bindian bank\b", "Indian Bank"), (r"\bbank of india\b", "Bank of India"),
]]

IFSC_RE = re.compile(r"\b([A-Z]{4})0[A-Z0-9]{6}\b")


_TABLE_WORDS = re.compile(r"\b(withdrawals?|deposits?|debits?|credits?|balance|narration|particulars)\b", re.I)


def header_text(text: str, max_lines: int = 15) -> str:
    """The title block of a statement: everything above the transaction table. A bank names itself there; narrations
    further down mention OTHER banks ("NEFT TO ICICI 5678")."""
    out = []
    for line in (text or "").splitlines()[:max_lines]:
        if len(_TABLE_WORDS.findall(line)) >= 2:
            break
        out.append(line)
    return "\n".join(out)


def identify_bank(ifsc: Optional[str] = None, text: str = "") -> Optional[dict]:
    """{"name", "code", "source"} or None. An IFSC code is trusted over the wording of the statement.
    Only the title block is searched, so a transfer narration naming another bank cannot change the answer."""
    text = header_text(text)
    candidates = [ifsc or ""]
    m = IFSC_RE.search(text.upper())
    if m:
        candidates.append(m.group(0))
    for c in candidates:
        c = c.strip().upper()
        if len(c) >= 4 and c[:4] in IFSC_BANKS and (len(c) == 4 or re.fullmatch(r"[A-Z]{4}0[A-Z0-9]{6}", c)):
            return {"name": IFSC_BANKS[c[:4]], "code": c[:4], "source": "ifsc"}
    for rx, name in _NAME_HINTS:
        if rx.search(text):
            code = next((k for k, v in IFSC_BANKS.items() if v == name), None)
            return {"name": name, "code": code, "source": "name"}
    return None
