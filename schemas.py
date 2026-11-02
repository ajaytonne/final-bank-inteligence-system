import datetime as dt
from decimal import Decimal
from typing import Generic, Literal, Optional, TypeVar

from pydantic import BaseModel, Field, field_validator, model_validator

T = TypeVar("T")

Source = Literal["pdf_text", "ocr", "llm", "derived", "user", "none"]


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
