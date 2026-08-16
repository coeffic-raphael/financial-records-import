"""Request and response DTOs.

No SQLAlchemy model is ever serialized directly. This is a security control, not
a style preference: an explicit allowlist means a column added later (a password
hash, an internal field) cannot silently appear in a response.
"""

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, PlainSerializer


def _serialize_money(value: Decimal | None) -> str | None:
    """Amounts leave as JSON strings.

    A JSON number is parsed back into a float by `JSON.parse`, losing precision
    before the value is even displayed. The frontend never recomputes
    gross + tax - fee; it renders the expected value the server provides.
    """
    return None if value is None else f"{value:.2f}"


Money = Annotated[Decimal | None, PlainSerializer(_serialize_money, return_type=str | None)]

BUSINESS_FIELDS = (
    "reference",
    "transaction_date",
    "value_date",
    "description",
    "gross_amount",
    "fee_amount",
    "tax_amount",
    "net_amount",
    "currency",
    "counterparty_name",
    "counterparty_account",
    "country",
    "category",
    "invoice_number",
    "payment_method",
)


class ErrorOut(BaseModel):
    code: str
    message: str
    details: dict | None = None


class ValidationErrorOut(BaseModel):
    field: str
    code: str
    message: str


class BatchCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=200)


class BatchOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    name: str
    created_at: datetime


class RecordOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    batch_id: str

    reference: str | None
    transaction_date: date | None
    value_date: date | None
    description: str | None
    gross_amount: Money
    fee_amount: Money
    tax_amount: Money
    net_amount: Money
    currency: str | None
    counterparty_name: str | None
    counterparty_account: str | None
    country: str | None
    category: str | None
    invoice_number: str | None
    payment_method: str | None

    source_type: str
    source_document_name: str
    extraction_confidence: Money
    field_confidence: dict | None

    status: str
    validation_errors: list[ValidationErrorOut]

    created_at: datetime
    updated_at: datetime


class RecordPatch(BaseModel):
    """Correction payload.

    Every field is a raw string, because a correction is merged into
    `raw_payload` and replayed through the exact same normalization the import
    uses. A user may therefore type "1 200,00" and have it normalized.

    `extra="forbid"` is what enforces that `status` is NOT writable: sending it
    returns 422 rather than being silently ignored. If status were patchable, a
    client could declare itself VALIDATED without server-side validation --
    which the assignment explicitly forbids.
    """

    model_config = ConfigDict(extra="forbid")

    reference: str | None = None
    transaction_date: str | None = None
    value_date: str | None = None
    description: str | None = None
    gross_amount: str | None = None
    fee_amount: str | None = None
    tax_amount: str | None = None
    net_amount: str | None = None
    currency: str | None = None
    counterparty_name: str | None = None
    counterparty_account: str | None = None
    country: str | None = None
    category: str | None = None
    invoice_number: str | None = None
    payment_method: str | None = None


class ImportResult(BaseModel):
    document_name: str
    imported: int
    by_status: dict[str, int]


class CurrencyTotal(BaseModel):
    """Never sum across currencies: adding EUR to USD is accounting nonsense."""

    currency: str
    net_amount: Money


class DocumentCount(BaseModel):
    source_document_name: str
    count: int


class BatchSummary(BaseModel):
    batch_id: str
    batch_name: str
    total_records: int
    by_status: dict[str, int]
    by_source_type: dict[str, int]
    documents: list[DocumentCount]
    extraction_jobs: dict[str, int]
    totals_by_currency: list[CurrencyTotal]
