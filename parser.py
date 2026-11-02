import re
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any, Optional

from app.services.normalize import (
    AMOUNT_RE,
    DATE_PATTERN,
    DATE_START_RE,
    amount_side,
    clean_text,
    mask_account_number,
    parse_amount,
    parse_date,
)
from app.services.text_extraction import DocumentText, Line, Word

PDF_BASE = 0.95

COLUMN_KEYWORDS: list[tuple[str, tuple[str, ...]]] = [
    ("effective_date", ("effective date", "effective_date", "value date", "value dt")),
    ("value_date", ("value date", "value dt")),
    ("date", ("txn date", "tran date", "transaction date", "date", "dt")),
    ("reference", ("ref", "refno", "reference", "chq", "chqno", "cheque", "ref no", "ref. no")),
    ("description", ("description", "narration", "particulars", "details", "remarks")),
    ("withdrawal", ("withdrawal", "withdrawals", "debit", "debits", "dr", "withdrawal amt")),
    ("deposit", ("deposit", "deposits", "credit", "credits", "cr", "deposit amt")),
    ("balance", ("balance", "closing balance", "bal")),
]
AMOUNT_COLS = ("withdrawal", "deposit", "balance")

HOLDER_RE = re.compile(
    r"^(?:account\s*holder(?:'?s)?(?:\s*name)?|account\s*name|customer\s*name|name\s*:)\s*[:\-]?\s*(.+)$",
    re.IGNORECASE,
)
ACCT_RE = re.compile(
    r"^(?:account|a/c|acct)\.?\s*(?:no|number|num)?\.?\s*[:\-]?\s*([0-9Xx*•][0-9Xx*•\s\-]{3,30})$",
    re.IGNORECASE,
)
PERIOD_RE = re.compile(
    rf"(?:statement\s*period|period|from)\s*(?:of\s*)?[:\-]?\s*({DATE_PATTERN})\s*(?:to|till|until|-|–)\s*({DATE_PATTERN})",
    re.IGNORECASE,
)
OPEN_RE = re.compile(r"opening\s*balance|balance\s*b/?f|brought\s*forward", re.IGNORECASE)
CLOSE_RE = re.compile(r"closing\s*balance|balance\s*c/?f|carried\s*forward", re.IGNORECASE)
FOOTER_RE = re.compile(
    r"(?:^\s*(total|grand total|end of statement|this is a computer|copyright|customer care|\*{3})|\bpage\s*(?:no\.?\s*)?\d+)",
    re.IGNORECASE,
)
REF_RE = re.compile(r"\b(?=[A-Z0-9]*\d)[A-Z0-9]{6,20}\b")
NAME_OK_RE = re.compile(r"[A-Za-z][A-Za-z .'\-]{1,79}")


@dataclass
class FieldGuess:
    value: Any = None
    confidence: float = 0.0
    source: str = "none"
    note: Optional[str] = None
    required: bool = True


@dataclass
class RawRow:
    index: int
    page: int
    source: str
    date: FieldGuess
    description: FieldGuess
    reference: FieldGuess
    deposit: FieldGuess
    withdrawal: FieldGuess
    balance: FieldGuess
    unassigned: Optional[Decimal] = None
    side_hint: Optional[str] = None
    issues: list[str] = field(default_factory=list)
    effective_date: FieldGuess = field(default_factory=lambda: FieldGuess(required=False))


@dataclass
class ParsedStatement:
    header: dict[str, FieldGuess]
    rows: list[RawRow]
    warnings: list[str] = field(default_factory=list)


# Confidence helpers


def words_conf(words: list[Word], source: str) -> float:
    if source == "pdf_text":
        return PDF_BASE
    if not words:
        return 0.0
    return round(min(max(sum(w.conf for w in words) / len(words) / 100, 0.0), 0.99), 3)


def guess(value, words, source, factor=1.0, note=None, required=True) -> FieldGuess:
    if value is None:
        return FieldGuess(None, 0.0, "none", note, required)
    return FieldGuess(value, round(words_conf(words, source) * factor, 3), source, note, required)


# Header


def segments(line: Line) -> list[tuple[str, list[Word]]]:
    out: list[tuple[str, list[Word]]] = []
    cells = line.cells
    i = 0
    while i < len(cells):
        words = list(cells[i])
        text = " ".join(w.text for w in words)
        if text.rstrip().endswith(":") and i + 1 < len(cells):
            words += cells[i + 1]
            i += 1
        out.append((" ".join(w.text for w in words), words))
        i += 1
    return out


def last_amount(text: str) -> Optional[Decimal]:
    found = [m.group(0) for m in AMOUNT_RE.finditer(text)]
    for tok in reversed(found):
        val = parse_amount(tok)
        if val is not None:
            return val
    return None


def parse_header(lines: list[Line], dayfirst: bool) -> dict[str, FieldGuess]:
    h: dict[str, FieldGuess] = {
        k: FieldGuess(required=k not in {"bank_name", "branch_name", "account_type", "ifsc"})
        for k in (
            "bank_name",
            "branch_name",
            "account_holder",
            "account_number_masked",
            "account_type",
            "ifsc",
            "period_start",
            "period_end",
            "opening_balance",
            "closing_balance",
        )
    }
    branch_mode = False
    branch_x: Optional[float] = None
    holder_mode = False
    holder_x: Optional[float] = None
    account_scan = False
    account_x: Optional[float] = None
    summary_columns: dict[str, float] = {}
    summary_page: Optional[int] = None
    for line in lines:
        src = line.source
        full = clean_text(line.text) or ""
        upper = full.upper()
        cell_texts = [(clean_text(" ".join(w.text for w in cell)) or "", cell) for cell in line.cells]
        for cell_text, cell_words in cell_texts:
            cell_upper = cell_text.upper()
            cell_x = min((w.x0 for w in cell_words), default=0.0)
            if "YOUR BRANCH DETAILS" in cell_upper:
                branch_mode, branch_x = True, cell_x
            if re.fullmatch(r"TO[, :]?", cell_text, re.IGNORECASE):
                holder_mode, holder_x = True, cell_x
            if re.search(r"\bACCOUNT\s+(?:NO\.?|NUMBER)\b", cell_text, re.IGNORECASE):
                account_scan, account_x = True, cell_x
            summary_key = "opening_balance" if OPEN_RE.search(cell_text) else "closing_balance" if CLOSE_RE.search(cell_text) else None
            if summary_key:
                summary_columns[summary_key] = (min(w.x0 for w in cell_words) + max(w.x1 for w in cell_words)) / 2
                summary_page = line.page

        if "TRAN DATE" in upper or "TRANSACTION DATE" in upper:
            account_scan = False
        if holder_mode and h["account_holder"].value is None:
            candidate_cell = next(((txt, ws) for txt, ws in cell_texts if holder_x is not None and abs(min(w.x0 for w in ws) - holder_x) <= 60 and txt and not re.search(r"\d", txt) and not re.fullmatch(r"TO[, :]?", txt, re.IGNORECASE)), None)
            if candidate_cell:
                candidate, words = candidate_cell
                if len(candidate) <= 80:
                    h["account_holder"] = guess(candidate, words, src, factor=0.8)
                    holder_mode = False
        if branch_mode and h["branch_name"].value is None:
            candidate_cell = next(((txt, ws) for txt, ws in cell_texts if branch_x is not None and min(w.x0 for w in ws) >= branch_x - 25 and txt and not re.search(r"\b(?:IFSC|MICR|NOMINEE|STATEMENT OF ACCOUNT|YOUR BRANCH DETAILS)\b", txt, re.IGNORECASE)), None)
            if candidate_cell:
                candidate, words = candidate_cell
                h["branch_name"] = guess(candidate, words, src, factor=0.8)
                branch_mode = False
        if account_scan and h["account_number_masked"].value is None and account_x is not None:
            acct_word = next((w for w in line.words if abs(w.x0 - account_x) <= 90 and re.fullmatch(r"[0-9Xx*•-]{6,24}", w.text)), None)
            if acct_word:
                masked = mask_account_number(acct_word.text)
                if masked:
                    h["account_number_masked"] = guess(masked, [acct_word], src, note="Account number masked for display")
                    account_scan = False

        # Summary values are often printed one row below their labels.
        if summary_columns and summary_page == line.page and not any(OPEN_RE.search(txt) or CLOSE_RE.search(txt) for txt, _ in cell_texts):
            amount_words = [w for w in line.words if parse_amount(w.text) is not None]
            for key, x in summary_columns.items():
                nearest = min(amount_words, key=lambda w: abs(w.xc - x), default=None)
                if nearest is not None and h[key].value is None:
                    h[key] = guess(parse_amount(nearest.text), [nearest], src)
            summary_columns = {}
            summary_page = None

        if h["bank_name"].value is None and re.search(r"\bBANK\b", upper) and len(full) < 120 and not re.search(r"\b(?:YOUR BRANCH|ACCOUNT|IFSC|SAVING|CURRENT)\b", upper) and ("COPYRIGHT" in upper or not re.search(r"\d", full)):
            candidate = re.sub(r"^COPYRIGHT\s*", "", full, flags=re.IGNORECASE).strip()
            bank_match = re.match(r"(.+?\bBANK(?:\s+(?:LIMITED|LTD\.?))?)\b", candidate, re.IGNORECASE)
            if bank_match:
                candidate = bank_match.group(1).strip()
            h["bank_name"] = guess(candidate, line.words, src, factor=0.8)
        if h["ifsc"].value is None and (m := re.search(r"\bIFSC\s*:?\s*([A-Z]{4}0[A-Z0-9]{6})\b", upper)):
            h["ifsc"] = guess(m.group(1), line.words, src)
        if h["account_type"].value is None and (m := re.search(r"\b(SAVING(?:S)?\s+BANK\s+A/C|CURRENT\s+A/C|SALARY\s+A/C|SAVING(?:S)?|CURRENT)\b", upper)):
            h["account_type"] = guess(m.group(1).title(), line.words, src)
        if h["account_number_masked"].value is None and (m := re.search(r"\bACCOUNT\s+(?:NO\.?|NUMBER)\s*[:#-]?\s*([0-9Xx*•][0-9Xx*• -]{3,30})", full, re.IGNORECASE)):
            raw = m.group(1).strip()
            masked = mask_account_number(raw)
            if masked:
                h["account_number_masked"] = guess(masked, line.words, src, note="Account number masked for display")
        for text, words in segments(line):
            if h["account_holder"].value is None and (m := HOLDER_RE.match(text)):
                name = clean_text(m.group(1))
                if name:
                    ok = bool(NAME_OK_RE.fullmatch(name))
                    h["account_holder"] = guess(
                        name, words, src, 1.0 if ok else 0.6,
                        None if ok else "Unusual characters in name",
                    )
            if h["account_number_masked"].value is None and (m := ACCT_RE.match(text)):
                raw = m.group(1)
                masked = mask_account_number(raw)
                if masked:
                    digits = sum(c.isdigit() for c in raw)
                    note = "Full number was masked by the system" if digits > 4 else None
                    h["account_number_masked"] = guess(masked, words, src, note=note)

        if h["period_start"].value is None and (m := PERIOD_RE.search(full)):
            start, end = parse_date(m.group(1), dayfirst), parse_date(m.group(2), dayfirst)
            h["period_start"] = guess(start, line.words, src, note=None if start else "Unreadable date")
            h["period_end"] = guess(end, line.words, src, note=None if end else "Unreadable date")
        if OPEN_RE.search(full) and h["opening_balance"].value is None:
            val = last_amount(full)
            if val is not None:
                h["opening_balance"] = guess(val, line.words, src)
        if CLOSE_RE.search(full):
            val = last_amount(full)
            if val is not None:
                h["closing_balance"] = guess(val, line.words, src)  # last wins
    return h


# Table columns


@dataclass
class Column:
    key: str
    x0: float
    x1: float


def classify_header_cell(text: str) -> Optional[str]:
    t = re.sub(r"[^a-z. ]", " ", text.lower()).strip()
    t = re.sub(r"\s+", " ", t)
    for key, kws in COLUMN_KEYWORDS:
        for kw in kws:
            if t == kw or t.startswith(kw + " ") or t.startswith(kw + "."):
                return key
    for key, kws in COLUMN_KEYWORDS:
        if any(len(kw) > 3 and kw in t for kw in kws):
            return key
    return None


def header_parts(words: list[Word]) -> list[tuple[str, float, float]]:
    """Split OCR-merged header words."""
    out = []
    for w in words:
        n = max(len(w.text), 1)
        per = (w.x1 - w.x0) / n
        for m in re.finditer(r"[A-Za-z.()]+", w.text):
            part = m.group(0).strip(".()")
            if part:
                out.append((part, w.x0 + m.start() * per, w.x0 + m.end() * per))
    return out


def detect_columns(line: Line) -> Optional[list[Column]]:
    low = line.text.lower()
    if "balance" not in low or not re.search(r"\bdate\b|\bdt\b", low):
        return None
    if not re.search(r"withdraw|debit|deposit|credit|\bdr\b|\bcr\b", low):
        return None
    cols: list[Column] = []
    prev_part = ""
    prev_x0 = 0.0
    for part, x0, x1 in header_parts(line.words):
        key = classify_header_cell(part)
        if key == "date" and prev_part.lower() in {"value", "effective"}:
            key = "effective_date" if prev_part.lower() == "effective" else "value_date"
            x0 = prev_x0
        prev_part = part
        if not key:
            prev_x0 = x0
            continue
        if cols and cols[-1].key == key:
            cols[-1].x1 = x1  # merge phrase
        elif key not in {c.key for c in cols}:
            cols.append(Column(key, x0, x1))
        prev_x0 = x0
    keys = {c.key for c in cols}
    if not {"date", "balance"} <= keys:
        return None
    return sorted(cols, key=lambda c: c.x0)


def assign_words(words: list[Word], cols: list[Column]) -> dict[str, list[Word]]:
    """Text cols are left-aligned; amount cols right-aligned."""
    out: dict[str, list[Word]] = {c.key: [] for c in cols}
    text_cols = [c for c in cols if c.key not in AMOUNT_COLS]
    amt_cols = [c for c in cols if c.key in AMOUNT_COLS]
    amt_start = min((c.x0 for c in amt_cols), default=1e9)
    for w in words:
        if not re.search(r"[A-Za-z0-9]", w.text):
            continue  # noise
        pad = 0.6 * w.height
        if amt_cols and (w.x1 >= amt_start - pad) and (parse_amount(w.text) is not None or w.x0 >= amt_start - pad):
            if parse_amount(w.text) is not None:
                col = min(amt_cols, key=lambda c: abs(c.x1 - w.x1))
            else:
                col = min(amt_cols, key=lambda c: abs((c.x0 + c.x1) / 2 - w.xc))
            out[col.key].append(w)
            continue
        candidates = []
        for i, candidate in enumerate(text_cols):
            left = float("-inf")
            if i:
                gap = candidate.x0 - text_cols[i - 1].x0
                left = candidate.x0 - min(gap * 0.5, 20.0)
            right = float("inf")
            if i + 1 < len(text_cols):
                gap = text_cols[i + 1].x0 - candidate.x0
                right = text_cols[i + 1].x0 - min(gap * 0.5, 20.0)
            if left - pad <= w.xc < right - pad * 0.2:
                candidates.append(candidate)
        col = candidates[0] if candidates else (min(text_cols, key=lambda c: abs(c.x0 - w.xc)) if text_cols else cols[0])
        out[col.key].append(w)
    return out


def _txt(ws: list[Word]) -> str:
    return " ".join(w.text for w in ws).strip()


# Row parsing


def parse_row_columns(line: Line, cols: list[Column], index: int, dayfirst: bool) -> Optional[RawRow]:
    parts = assign_words(line.words, cols)
    src = line.source
    date_words = parts.get("date", [])
    d = parse_date(_txt(date_words), dayfirst)
    if d is None:
        m = DATE_START_RE.match(line.text)
        d = parse_date(m.group(1), dayfirst) if m else None
    if d is None:
        return None

    row = RawRow(
        index=index,
        page=line.page,
        source=src,
        date=guess(d, date_words, src),
        description=FieldGuess(),
        reference=FieldGuess(required=False),
        deposit=FieldGuess(required=False),
        withdrawal=FieldGuess(required=False),
        balance=FieldGuess(),
    )
    effective_words = parts.get("effective_date", parts.get("value_date", []))
    effective_value = parse_date(_txt(effective_words), dayfirst)
    row.effective_date = guess(effective_value, effective_words, src, required=False, note=None if effective_value else "Not present")

    desc_words = parts.get("description", [])
    desc = clean_text(_txt(desc_words))
    row.description = guess(desc, desc_words, src, note=None if desc else "Description missing")

    ref_words = parts.get("reference", [])
    ref = clean_text(_txt(ref_words))
    row.reference = guess(ref, ref_words, src, required=False, note=None if ref else "Not present")

    for key in AMOUNT_COLS:
        ws = parts.get(key, [])
        text = _txt(ws)
        if not text or text in {"-", "--"}:
            setattr(row, key, FieldGuess(None, 0.0, "none", None, key == "balance"))
            continue
        val = parse_amount(text)
        if val is None:
            setattr(row, key, FieldGuess(None, 0.0, "none", f"Unreadable amount '{text}'", True))
            row.issues.append(f"Unreadable {key} value")
            continue
        if key != "balance":
            val = abs(val)
        setattr(row, key, guess(val, ws, src, required=key == "balance"))
    if row.deposit.value is None and row.withdrawal.value is None:
        row.issues.append("No deposit or withdrawal amount found")
    return row


def parse_row_positional(line: Line, index: int, dayfirst: bool) -> Optional[RawRow]:
    text = line.text
    m = DATE_START_RE.match(text)
    if not m:
        return None
    d = parse_date(m.group(1), dayfirst)
    if d is None:
        return None
    rest = text[m.end():]
    amounts = list(AMOUNT_RE.finditer(rest))
    src = line.source
    factor = 0.85  # no header layout
    words = line.words
    row = RawRow(
        index=index,
        page=line.page,
        source=src,
        date=guess(d, words, src),
        description=FieldGuess(),
        reference=FieldGuess(required=False),
        deposit=FieldGuess(required=False),
        withdrawal=FieldGuess(required=False),
        balance=FieldGuess(),
    )
    # Positional fallback keeps the second date when it immediately follows the transaction date.
    date_matches = list(re.finditer(DATE_PATTERN, text, re.IGNORECASE))
    if len(date_matches) > 1:
        effective_value = parse_date(date_matches[1].group(0), dayfirst)
        row.effective_date = guess(effective_value, words, src, factor, required=False)
    body = rest
    if amounts:
        body = rest[: amounts[0].start()]
        bal_tok = amounts[-1].group(0)
        bal = parse_amount(bal_tok)
        row.balance = guess(bal, words, src, factor)
        if len(amounts) >= 3:
            wd = parse_amount(amounts[-3].group(0))
            dp = parse_amount(amounts[-2].group(0))
            row.withdrawal = guess(abs(wd) if wd else None, words, src, factor * 0.9, required=False)
            row.deposit = guess(abs(dp) if dp else None, words, src, factor * 0.9, required=False)
        elif len(amounts) == 2:
            tok = amounts[0].group(0)
            val = parse_amount(tok)
            row.unassigned = abs(val) if val is not None else None
            row.side_hint = amount_side(tok)
        else:
            row.issues.append("Only one amount found on row")
    else:
        row.issues.append("No amounts found on row")

    body = clean_text(body) or ""
    refs = [r for r in REF_RE.findall(body) if not re.fullmatch(r"\d{1,5}", r)]
    ref = refs[-1] if refs else None
    if ref:
        body = clean_text(body.replace(ref, " ")) or ""
    row.reference = guess(ref, words, src, factor, note=None if ref else "Not present", required=False)
    row.description = guess(body or None, words, src, factor, note=None if body else "Description missing")
    return row


def is_summary_line(text: str) -> bool:
    return bool(OPEN_RE.search(text) or CLOSE_RE.search(text) or FOOTER_RE.search(text))


def parse_transactions(
    doc: DocumentText,
    dayfirst: bool,
    period_start: Optional[date] = None,
    period_end: Optional[date] = None,
) -> tuple[list[RawRow], list[str]]:
    rows: list[RawRow] = []
    warnings: list[str] = []
    cols_by_source: dict[str, list[Column]] = {}
    in_table = False
    used_positional = False
    for page in doc.pages:
        cols = None
        for line in page.lines:
            detected = detect_columns(line)
            if detected:
                cols = detected
                cols_by_source[line.source] = detected
                in_table = True
                continue
            text = line.text
            if is_summary_line(text):
                continue
            if not DATE_START_RE.match(text):
                # Continuation line
                if in_table and rows and rows[-1].page == line.page:
                    prev = rows[-1]
                    extra = clean_text(text)
                    if extra and prev.description.value and len(extra) < 120:
                        prev.description.value = f"{prev.description.value} {extra}"
                continue
            line_date_match = DATE_START_RE.match(text)
            line_date = parse_date(line_date_match.group(1), dayfirst) if line_date_match else None
            if line_date is not None and ((period_start and line_date < period_start) or (period_end and line_date > period_end)):
                continue
            active = cols if cols is not None else cols_by_source.get(line.source)
            row = parse_row_columns(line, active, len(rows), dayfirst) if active else None
            if row is not None and row.issues:
                alt = parse_row_positional(line, len(rows), dayfirst)
                if alt is not None and len(alt.issues) < len(row.issues):
                    row = alt
                    used_positional = True
            if row is None:
                row = parse_row_positional(line, len(rows), dayfirst)
                if row is not None:
                    used_positional = True
            if row is None:
                continue
            if (period_start and row.date.value < period_start) or (period_end and row.date.value > period_end):
                continue
            # Reject header-ish dates
            if (
                row.balance.value is None
                and row.deposit.value is None
                and row.withdrawal.value is None
                and row.unassigned is None
            ):
                continue
            in_table = True
            rows.append(row)
    if used_positional:
        warnings.append(
            "Some rows were parsed without a recognised table header; "
            "deposit/withdrawal sides were inferred from balances."
        )
    return rows, warnings


def parse_statement(doc: DocumentText, dayfirst: bool = True) -> ParsedStatement:
    header = parse_header(doc.lines, dayfirst)
    rows, warnings = parse_transactions(
        doc, dayfirst, header["period_start"].value, header["period_end"].value
    )
    return ParsedStatement(header=header, rows=rows, warnings=warnings)
