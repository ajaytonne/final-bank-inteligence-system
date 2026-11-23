import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

MONTHS = r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*"

DATE_PATTERN = (
    r"(?:\d{1,2}[/\-.]\d{1,2}[/\-.]\d{2,4}"
    r"|\d{4}-\d{2}-\d{2}"
    rf"|\d{{1,2}}[\s\-/]{MONTHS}[\s\-/,]*\d{{2,4}}"
    rf"|{MONTHS}\s+\d{{1,2}},?\s+\d{{4}})"
)
DATE_RE = re.compile(DATE_PATTERN, re.IGNORECASE)
DATE_START_RE = re.compile(rf"^\s*({DATE_PATTERN})", re.IGNORECASE)

AMOUNT_PATTERN = (
    r"(?:(?:INR|Rs\.?|₹)\s*)?"
    r"\(?-?\d{1,3}(?:,\d{2,3})+(?:\.\d{1,2})?\)?"
    r"|(?:(?:INR|Rs\.?|₹)\s*)?\(?-?\d+\.\d{2}\)?"
)
AMOUNT_RE = re.compile(rf"(?<![\w.])({AMOUNT_PATTERN})(?:\s*(Cr|Dr|CR|DR)\b)?(?![\w])")
FULL_AMOUNT_RE = re.compile(rf"^\s*({AMOUNT_PATTERN})\s*(Cr|Dr|CR|DR)?\.?\s*$")

_OCR_DIGIT_FIX = str.maketrans({"O": "0", "o": "0", "l": "1", "I": "1", "S": "5"})


def parse_date(text: str | None, dayfirst: bool = True) -> date | None:
    if not text:
        return None
    s = re.sub(r"\s+", " ", text.strip().replace(",", " ")).strip()
    s = re.sub(r"(?i)\bsept\b", "Sep", s)
    numeric = re.fullmatch(r"(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{2,4})", s)
    if numeric:
        a, b, y = numeric.groups()
        d, m = (a, b) if dayfirst else (b, a)
        year = int(y)
        if year < 100:
            year += 2000 if year < 70 else 1900
        try:
            return date(year, int(m), int(d))
        except ValueError:
            try:
                return date(year, int(d), int(m))  # swapped fallback
            except ValueError:
                return None
    s = re.sub(r"[\-/]", " ", s)
    for fmt in ("%Y %m %d", "%d %b %Y", "%d %B %Y", "%d %b %y", "%d %B %y", "%b %d %Y", "%B %d %Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def parse_amount(text: str | None) -> Decimal | None:
    if text is None:
        return None
    s = text.strip()
    if not s or s in {"-", "--", "—", "NIL", "nil"}:
        return None
    m = FULL_AMOUNT_RE.match(s)
    if not m:
        fixed = s.translate(_OCR_DIGIT_FIX)
        m = FULL_AMOUNT_RE.match(fixed)
        if not m:
            return None
    raw, suffix = m.group(1), m.group(2)
    negative = raw.strip().startswith("(") or "-" in raw or (suffix or "").lower() == "dr"
    digits = re.sub(r"^\(?\s*(?:INR|Rs\.?|₹)", "", raw.strip(), flags=re.IGNORECASE)
    digits = re.sub(r"[^\d.]", "", digits)
    try:
        value = Decimal(digits).quantize(Decimal("0.01"))
    except InvalidOperation:
        return None
    return -value if negative else value


def amount_side(text: str | None) -> str | None:
    if not text:
        return None
    m = re.search(r"\b(Cr|Dr)\.?\s*$", text.strip(), re.IGNORECASE)
    return m.group(1).lower() if m else None


def is_amount(text: str) -> bool:
    return parse_amount(text) is not None


def mask_account_number(raw: str | None) -> str | None:
    if not raw:
        return None
    cleaned = re.sub(r"[\s\-]", "", raw.strip())
    if not re.fullmatch(r"[0-9Xx*•]{4,24}", cleaned):
        return None
    visible = re.findall(r"\d", cleaned)
    if len(visible) < 2 and not re.search(r"[Xx*•]", cleaned):
        return None
    last4 = cleaned[-4:]
    if not last4.isdigit():
        tail = "".join(visible[-4:])
        return ("X" * 8) + tail if tail else None
    return "X" * max(len(cleaned) - 4, 4) + last4


def clean_text(s: str | None) -> str | None:
    if s is None:
        return None
    tokens = [t for t in s.split() if re.search(r"[A-Za-z0-9₹]", t)]  # drop noise
    s = " ".join(tokens).strip(" :|-\t")
    return s or None
