import logging
import re

from app.config import Settings
from app.schemas import ExtractedField, ExtractionResult, StatementHeader, Transaction
from app.services import llm
from app.services.file_validation import ValidatedFile
from app.services.parser import FieldGuess, RawRow, parse_statement
from app.services.text_extraction import DocumentText, extract_image, extract_pdf
from app.services.validation import validate_balances

log = logging.getLogger(__name__)

MAX_RAW_TEXT = 20_000
LONG_NUMBER_RE = re.compile(r"\b(\d[\d ]{7,22}\d)\b")


def redact(text: str) -> str:
    """Mask account-like numbers."""

    def _mask(m: re.Match) -> str:
        digits = m.group(1).replace(" ", "")
        if len(digits) < 9:
            return m.group(0)
        return "X" * (len(digits) - 4) + digits[-4:]

    return LONG_NUMBER_RE.sub(_mask, text)


def to_field(g: FieldGuess, threshold: float) -> ExtractedField:
    if g.value is None:
        return ExtractedField(
            value=None,
            confidence=0.0,
            needs_review=g.required,
            source="none",
            note=g.note or ("Not found" if g.required else None),
        )
    review = g.confidence < threshold or g.source in ("llm", "derived")
    return ExtractedField(
        value=g.value,
        confidence=g.confidence,
        needs_review=review,
        source=g.source,
        note=g.note,
    )


def to_transaction(r: RawRow, threshold: float) -> Transaction:
    fields = {
        k: to_field(getattr(r, k), threshold)
        for k in ("date", "effective_date", "description", "reference", "deposit", "withdrawal", "balance")
    }
    present_amount = [fields[k] for k in ("deposit", "withdrawal") if fields[k].value is not None]
    core = [fields["date"], fields["balance"], fields["description"], *present_amount]
    conf = min((f.confidence for f in core), default=0.0)
    review = bool(r.issues) or any(f.needs_review for f in fields.values())
    return Transaction(
        row_index=r.index,
        page=r.page,
        confidence=round(conf, 3),
        needs_review=review,
        issues=r.issues,
        **fields,
    )


def method_of(doc: DocumentText) -> str:
    if not doc.pages or not doc.lines:
        return "none"
    srcs = {p.source for p in doc.pages}
    return "mixed" if len(srcs) > 1 else srcs.pop()


def run_extraction(file: ValidatedFile, settings: Settings) -> ExtractionResult:
    doc = extract_pdf(file.data, settings) if file.kind == "pdf" else extract_image(file.data, settings)
    warnings = list(doc.warnings)
    text = doc.text
    if not text.strip():
        warnings.append("No readable text was found in the document.")

    parsed = parse_statement(doc, settings.date_dayfirst)
    warnings += parsed.warnings

    llm_used, llm_warn = llm.fill_missing_header(parsed.header, text, settings)
    warnings += llm_warn

    validation = validate_balances(parsed)
    if validation.status == "failed":
        warnings.append("Balance check failed; flagged rows need review.")
    if not parsed.rows and text.strip():
        warnings.append("No transaction rows were recognised.")

    th = settings.review_threshold
    header = StatementHeader(**{k: to_field(g, th) for k, g in parsed.header.items()})
    txns = [to_transaction(r, th) for r in parsed.rows]

    review_count = sum(1 for f in header.model_dump().values() if f["needs_review"])
    review_count += sum(1 for t in txns if t.needs_review)

    return ExtractionResult(
        file_name=file.name,
        file_type=file.kind,
        method=method_of(doc),
        page_count=len(doc.pages),
        ocr_pages=doc.ocr_pages,
        llm_used=llm_used,
        header=header,
        transactions=txns,
        validation=validation,
        review_required_count=review_count,
        warnings=warnings,
        raw_text=redact(text[:MAX_RAW_TEXT]),
    )
