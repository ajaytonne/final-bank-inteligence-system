import datetime as dt
from decimal import Decimal
from typing import Generic, Literal, Optional, TypeVar

from pydantic import BaseModel, Field, field_validator, model_validator

T = TypeVar("T")

Source = Literal["pdf_text", "ocr", "llm", "derived", "user", "none"]

# Keep in sync with CATEGORIES in frontend/src/utils/review.js
Category = Literal[
    "Food", "Shopping", "Salary", "Bills", "Transport", "Entertainment", "Health", "Education", "Other"
]


class ExtractedField(BaseModel, Generic[T]):
    value: Optional[T] = None
    confidence: float = Field(0.0, ge=0.0, le=1.0)
    needs_review: bool = True
    source: Source = "none"
    note: Optional[str] = None


class StatementHeader(BaseModel):
    bank_name: ExtractedField[str] = ExtractedField[str]()
    branch_name: ExtractedField[str] = ExtractedField[str]()
    account_holder: ExtractedField[str] = ExtractedField[str]()
    account_number_masked: ExtractedField[str] = ExtractedField[str]()
    account_type: ExtractedField[str] = ExtractedField[str]()
    ifsc: ExtractedField[str] = ExtractedField[str]()
    currency: ExtractedField[str] = ExtractedField[str](value="INR", confidence=1.0, needs_review=False, source="derived")
    period_start: ExtractedField[dt.date] = ExtractedField[dt.date]()
    period_end: ExtractedField[dt.date] = ExtractedField[dt.date]()
    opening_balance: ExtractedField[Decimal] = ExtractedField[Decimal]()
    closing_balance: ExtractedField[Decimal] = ExtractedField[Decimal]()


class Transaction(BaseModel):
    row_index: int
    page: int
    date: ExtractedField[dt.date]
    description: ExtractedField[str]
    reference: ExtractedField[str]
    deposit: ExtractedField[Decimal]
    withdrawal: ExtractedField[Decimal]
    balance: ExtractedField[Decimal]
    confidence: float = Field(0.0, ge=0.0, le=1.0)
    needs_review: bool = False
    issues: list[str] = []
    effective_date: ExtractedField[dt.date] = ExtractedField[dt.date]()


class BalanceValidation(BaseModel):
    status: Literal["passed", "failed", "unavailable"]
    computed_closing: Optional[Decimal] = None
    stated_closing: Optional[Decimal] = None
    mismatched_rows: list[int] = []
    note: Optional[str] = None


class ExtractionResult(BaseModel):
    file_name: str
    file_type: Literal["pdf", "image"]
    method: Literal["pdf_text", "ocr", "mixed", "none"]
    page_count: int
    ocr_pages: list[int] = []
    llm_used: bool = False
    header: StatementHeader
    transactions: list[Transaction]
    validation: BalanceValidation
    review_required_count: int
    warnings: list[str] = []
    raw_text: str = ""
    confidence_note: str = (
        "Confidence values are heuristic review indicators, "
        "not calibrated probabilities."
    )


# Reviewed payload


class ReviewedHeader(BaseModel):
    bank_name: Optional[str] = Field(None, max_length=200)
    branch_name: Optional[str] = Field(None, max_length=200)
    account_holder: Optional[str] = Field(None, max_length=200)
    account_number_masked: Optional[str] = Field(None, max_length=40)
    account_type: Optional[str] = Field(None, max_length=100)
    currency: str = Field("INR", min_length=3, max_length=3, pattern="^[A-Z]{3}$")
    ifsc: Optional[str] = Field(None, max_length=20)
    period_start: Optional[dt.date] = None
    period_end: Optional[dt.date] = None
    opening_balance: Optional[Decimal] = Field(None, max_digits=18, decimal_places=2)
    closing_balance: Optional[Decimal] = Field(None, max_digits=18, decimal_places=2)

    @field_validator("account_number_masked")
    @classmethod
    def must_be_masked(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        digits = [c for c in v if c.isdigit()]
        if len(digits) > 4:
            raise ValueError("account number must be masked (max 4 visible digits)")
        return v

    @model_validator(mode="after")
    def period_order(self):
        if self.period_start and self.period_end and self.period_start > self.period_end:
            raise ValueError("period_start must be on or before period_end")
        return self


class ReviewedTransaction(BaseModel):
    date: Optional[dt.date] = None
    effective_date: Optional[dt.date] = None
    description: Optional[str] = Field(None, max_length=500)
    reference: Optional[str] = Field(None, max_length=100)
    deposit: Optional[Decimal] = Field(None, ge=0, max_digits=18, decimal_places=2)
    withdrawal: Optional[Decimal] = Field(None, ge=0, max_digits=18, decimal_places=2)
    balance: Optional[Decimal] = Field(None, max_digits=18, decimal_places=2)
    # Old saved statements have no category, so they load as "Other".
    category: Category = "Other"

    @model_validator(mode="after")
    def one_side_only(self):
        if self.deposit and self.withdrawal:
            raise ValueError("a row cannot have both deposit and withdrawal")
        return self


class ReviewedStatement(BaseModel):
    file_name: str = Field(..., max_length=255)
    header: ReviewedHeader
    transactions: list[ReviewedTransaction] = Field(default_factory=list, max_length=5000)
    reviewer_note: Optional[str] = Field(None, max_length=1000)
    review_metadata: Optional["ReviewMetadata"] = None
    # What the reviewer edited before saving. Goes to the audit trail only; never stored in the statement.
    changes: list["FieldChange"] = Field(default_factory=list, max_length=2000)


class ReviewMetadata(BaseModel):
    extraction_method: Literal["pdf_text", "ocr", "mixed", "none"]
    average_confidence: float = Field(ge=0.0, le=1.0)
    field_count: int = Field(ge=0)
    ocr_field_count: int = Field(ge=0)
    pdf_text_field_count: int = Field(ge=0)
    derived_field_count: int = Field(ge=0)
    low_confidence_field_count: int = Field(ge=0)


class FieldChange(BaseModel):
    where: str = Field(..., max_length=40)  # "Header" or "Row 3"
    field: str = Field(..., max_length=60)
    old: Optional[str] = Field(None, max_length=500)
    new: Optional[str] = Field(None, max_length=500)


ReviewedStatement.model_rebuild()


class SavedStatement(BaseModel):
    id: int
    created_at: dt.datetime
    statement: ReviewedStatement


class SavedStatementSummary(BaseModel):
    id: int
    created_at: dt.datetime
    file_name: str
    account_holder: Optional[str]
    transaction_count: int


class HealthResponse(BaseModel):
    status: Literal["ok"]
    tesseract_available: bool
    ollama_enabled: bool
    ollama_reachable: bool


# ---- Merchant identification ---------------------------------------------------------------
# Derived data only: nothing here is stored inside a statement or changes a transaction.
MerchantCategory = Literal["Shopping", "Food", "Groceries", "Transport", "Utilities", "Entertainment", "Banking", "Other"]


class MerchantIdentifyRequest(BaseModel):
    descriptions: list[Optional[str]] = Field(default_factory=list, max_length=5000)

    @field_validator("descriptions")
    @classmethod
    def short_enough(cls, v):
        if any(d is not None and len(d) > 500 for d in v):
            raise ValueError("a description is longer than 500 characters")
        return v


class MerchantResult(BaseModel):
    merchant_name: str
    category: MerchantCategory
    platform: Optional[str] = None
    status: Literal["Identified", "User Corrected", "Unknown"]
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str
    source: Literal["system", "user", "none"]
    matched_alias: Optional[str] = None


class MerchantCorrection(BaseModel):
    narration: str = Field(..., min_length=1, max_length=500)
    merchant_name: str = Field(..., min_length=1, max_length=100)
    category: MerchantCategory
    alias: Optional[str] = Field(None, max_length=200)  # default: the cleaned narration


class MerchantMapping(BaseModel):
    id: int
    merchant_name: str
    aliases: list[str]
    category: MerchantCategory
    source: Literal["system", "user", "imported"]
    confidence_threshold: Optional[float] = None
    created_at: dt.datetime
    updated_at: dt.datetime


# ---- Bank accounts and reconciliation ------------------------------------------------------
# Results are derived data, stored in their own tables. They never change a saved statement.
ReconKind = Literal["internal", "inter_bank"]
ReconStatus = Literal[
    "Matched", "Possible Match", "Unmatched", "Duplicate Candidate", "Missing Transaction",
    "Timing Difference", "Manual Review", "Rejected Match",
]


def _masked(v: Optional[str]) -> Optional[str]:
    if v is not None and sum(c.isdigit() for c in v) > 4:
        raise ValueError("account number must be masked (max 4 visible digits)")
    return v


class BankAccountIn(BaseModel):
    bank_name: str = Field(..., min_length=1, max_length=100)
    account_label: str = Field(..., min_length=1, max_length=100)
    account_number_masked: Optional[str] = Field(None, max_length=40)
    ownership_confirmed: bool = False  # "this account is mine"; needed before a transfer can count as internal

    _mask = field_validator("account_number_masked")(_masked)


class BankAccountUpdate(BaseModel):
    bank_name: Optional[str] = Field(None, min_length=1, max_length=100)
    account_label: Optional[str] = Field(None, min_length=1, max_length=100)
    account_number_masked: Optional[str] = Field(None, max_length=40)
    ownership_confirmed: Optional[bool] = None

    _mask = field_validator("account_number_masked")(_masked)


class BankAccount(BankAccountIn):
    id: int
    created_at: dt.datetime
    updated_at: dt.datetime


class AssignAccount(BaseModel):
    account_id: Optional[int] = None  # null removes the assignment


class StatementAccount(BaseModel):
    statement_id: int
    account_id: Optional[int] = None


class ReconCreate(BaseModel):
    kind: ReconKind
    statement_a_id: int
    statement_b_id: int
    date_window_days: Optional[int] = Field(None, ge=0, le=7)  # default: 0 for internal, 2 for inter-bank


class ReconSession(BaseModel):
    id: int
    kind: ReconKind
    statement_a_id: int
    statement_b_id: int
    a_label: str
    b_label: str
    date_window_days: int
    status: Literal["created", "completed"]
    total_a: int
    total_b: int
    notes: list[str] = []
    created_at: dt.datetime
    updated_at: dt.datetime


class TxnSnapshot(BaseModel):
    date: Optional[dt.date] = None
    description: str = ""
    reference: str = ""
    amount: Decimal
    direction: Literal["debit", "credit"]


class ReconMatch(BaseModel):
    id: int
    session_id: int
    a_statement_id: Optional[int] = None
    a_index: Optional[int] = None
    b_statement_id: Optional[int] = None
    b_index: Optional[int] = None
    match_type: str
    status: ReconStatus
    reason: str
    confidence: float
    confirmation_status: Literal["auto", "pending", "confirmed", "rejected", "none"]
    internal_transfer: bool
    a_reference: Optional[str] = None
    b_reference: Optional[str] = None
    a: Optional[TxnSnapshot] = None
    b: Optional[TxnSnapshot] = None
    note: Optional[str] = None
    created_at: dt.datetime
    updated_at: dt.datetime


class ReconSummary(BaseModel):
    total_a: int
    total_b: int
    matched: int
    timing_differences: int
    possible_matches: int
    manual_review: int
    unmatched: int
    period_gaps: int = 0  # outside the other statement's dates; not errors
    missing_transactions: int
    duplicate_candidates: int
    rejected: int
    confirmed_internal_transfers: int
    total_matched_amount: Decimal
    total_unmatched_amount: Decimal


class ReconDetail(BaseModel):
    session: ReconSession
    summary: ReconSummary
    matches: list[ReconMatch]


class ReconDecision(BaseModel):
    note: Optional[str] = Field(None, max_length=500)


class Consolidated(BaseModel):
    income: Decimal
    expenses: Decimal
    savings: Decimal
    income_before_exclusion: Decimal
    expenses_before_exclusion: Decimal
    excluded_transfer_count: int
    excluded_amount: Decimal


# ---- Audit trail and duplicate checks -----------------------------------------------------------
class AuditEntry(BaseModel):
    id: int
    at: dt.datetime
    statement_id: Optional[int] = None
    action: Literal["saved", "edited", "deleted", "warning"]
    where: Optional[str] = None
    field: Optional[str] = None
    old: Optional[str] = None
    new: Optional[str] = None
    detail: Optional[str] = None


class StatementWarning(BaseModel):
    kind: Literal["duplicate", "overlap", "repeated_rows"]
    message: str
    statement_id: Optional[int] = None  # the saved statement it clashes with, when there is one
