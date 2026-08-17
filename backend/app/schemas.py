"""Request and response DTOs.

No SQLAlchemy model is ever serialized directly. This is a security control, not
a style preference: an explicit allowlist means a column added later (a password
hash, an internal field) cannot silently appear in a response.
"""

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Generic, TypeVar

from pydantic import (
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    PlainSerializer,
    StringConstraints,
    field_validator,
    model_validator,
)


def _serialize_money(value: Decimal | None) -> str | None:
    """Amounts leave as JSON strings.

    A JSON number is parsed back into a float by `JSON.parse`, losing precision
    before the value is even displayed. The frontend never recomputes
    gross + tax - fee; it renders the expected value the server provides.
    """
    return None if value is None else f"{value:.2f}"


Money = Annotated[Decimal | None, PlainSerializer(_serialize_money, return_type=str | None)]

# The request bounds its own size, like the page limit: a caller does not get
# to decide how much the server holds at once.
MAX_BULK_RECORDS = 200

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


class RegisterRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: EmailStr
    name: str = Field(min_length=1, max_length=120)
    password: str = Field(min_length=1)


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: str
    password: str


class UserOut(BaseModel):
    """No password field exists here, and that is the point of an explicit DTO."""

    model_config = ConfigDict(from_attributes=True)
    id: str
    email: str
    name: str
    tenant_id: str


class SessionOut(BaseModel):
    """The access token travels in the BODY, never in a cookie.

    The frontend keeps it in memory only. The refresh token is the opposite: an
    httpOnly cookie the JavaScript never sees.
    """

    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserOut


ItemT = TypeVar("ItemT")


class Page(BaseModel, Generic[ItemT]):
    """One slice of a list, plus the size of the whole.

    `total` is not decoration. The workflow asks a reviewer to see how many
    records still need review, and that number is a property of the filtered
    set, not of the page in front of them -- a count taken from `items` would
    silently become "up to 50" and misreport the work left to do.

    Offset paging rather than a cursor: a batch is a bounded set with a dense,
    stable order (`import_sequence`), and a reviewer works through it by
    jumping to a page. A cursor buys stability under concurrent inserts, which
    is not what happens here -- an import is finished before anyone reviews it.
    """

    items: list[ItemT]
    total: int
    limit: int
    offset: int


# Stripping happens before the length check, so a name of spaces is refused
# rather than stored as a batch with no readable title. Registration already
# refuses a blank name; a batch had no equivalent.
BatchName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]


class BatchCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: BatchName


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
    has_source_document: bool
    extraction_confidence: Money
    field_confidence: dict[str, float] | None

    status: str
    validation_errors: list[ValidationErrorOut]

    # What arrived, before normalisation and before anyone corrected it.
    # A reviewer comparing an extraction to its source needs to tell "the model
    # read this" from "someone typed this".
    raw_payload: dict

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


class BulkRecordPatch(BaseModel):
    """One correction, applied to several records of a single batch.

    `changes` reuses RecordPatch, so `extra="forbid"` and the refusal to write
    `status` hold here too. A bulk path that accepted what the single-record
    path rejects would be a way round the rule rather than a second door to it.
    """

    model_config = ConfigDict(extra="forbid")

    record_ids: list[str] = Field(min_length=1, max_length=MAX_BULK_RECORDS)
    changes: RecordPatch

    @field_validator("record_ids")
    @classmethod
    def _no_duplicates(cls, value: list[str]) -> list[str]:
        """Refused rather than deduplicated: `updated: 2` for one record would
        be a lie, and silently collapsing the list hides a client bug."""
        if len(set(value)) != len(value):
            raise ValueError("record_ids contains duplicates")
        return value

    @model_validator(mode="after")
    def _changes_are_usable(self) -> "BulkRecordPatch":
        """Checked here, not in the route.

        A ValueError raised inside a handler is a 500; raised during validation
        it is the 422 the client can act on. Both refusals below are about the
        shape of the request, so this is where they belong.
        """
        changes = self.applied_changes()
        if not changes:
            raise ValueError("changes must name at least one field")
        if "reference" in changes:
            raise ValueError(
                "reference cannot be corrected in bulk: one value across several "
                "records creates duplicates by construction"
            )
        return self

    def applied_changes(self) -> dict[str, str | None]:
        """Only the fields actually sent.

        Without `exclude_unset` every one of RecordPatch's fifteen fields comes
        back, fourteen of them None, and a correction to one field would erase
        the rest of the record.
        """
        return self.changes.model_dump(exclude_unset=True)


class BulkCorrectionResult(BaseModel):
    """What the click actually unblocked -- the number a reviewer is after."""

    updated: int
    by_status: dict[str, int]


class ImportResult(BaseModel):
    document_name: str
    imported: int
    by_status: dict[str, int]


class ExtractionJobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    batch_id: str
    document_name: str
    status: str
    provider: str | None
    model: str | None
    input_tokens: int | None
    output_tokens: int | None
    duration_ms: int | None
    record_count: int | None
    error: str | None
    created_at: datetime
    updated_at: datetime


class ExtractionAccepted(BaseModel):
    """Answer to a PDF upload: the work has been queued, not done."""

    jobs: list[ExtractionJobOut]


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
