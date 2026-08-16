"""Structured output contract and prompt.

Both live here, versioned together: a schema change and a prompt change are the
same change, and separating them makes extraction regressions hard to reason
about.
"""

from typing import Any

from pydantic import BaseModel, Field, field_validator

from app.domain.enums import Category, Currency, PaymentMethod
from app.domain.validation import REQUIRED_FIELDS

EXTRACTION_FIELDS = (
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


class ExtractedField(BaseModel):
    """A value together with how sure the model is about it."""

    value: str | None = Field(
        default=None, description="The value exactly as written, or null if absent."
    )
    confidence: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Certainty for this field alone, from 0.0 to 1.0.",
    )

    @field_validator("confidence", mode="before")
    @classmethod
    def _clamp(cls, value: object) -> object:
        """Bring an out-of-range confidence back into [0, 1] instead of failing.

        The bounds are declared in the schema so the provider is constrained at
        its end. This validator handles the case where it answers 1.5 anyway:
        rejecting would discard an otherwise usable extraction over a piece of
        metadata. Clamping an estimate loses nothing actionable -- the same
        reasoning that makes confidence the one value we round.
        """
        if isinstance(value, int | float):
            return min(1.0, max(0.0, float(value)))
        return value


class ExtractedRecord(BaseModel):
    """One financial record.

    EVERY FIELD IS OPTIONAL, deliberately. This schema checks STRUCTURE only:
    that the response is a list of objects with known keys. Whether a field is
    required is a business rule and belongs to the domain, which already knows
    it. The consequence is what the assignment asks for: an incomplete
    extraction does not fail parsing, it produces a record that validation flags
    and that is persisted as NEEDS_REVIEW.
    """

    reference: ExtractedField = ExtractedField()
    transaction_date: ExtractedField = ExtractedField()
    value_date: ExtractedField = ExtractedField()
    description: ExtractedField = ExtractedField()
    gross_amount: ExtractedField = ExtractedField()
    fee_amount: ExtractedField = ExtractedField()
    tax_amount: ExtractedField = ExtractedField()
    net_amount: ExtractedField = ExtractedField()
    currency: ExtractedField = ExtractedField()
    counterparty_name: ExtractedField = ExtractedField()
    counterparty_account: ExtractedField = ExtractedField()
    country: ExtractedField = ExtractedField()
    category: ExtractedField = ExtractedField()
    invoice_number: ExtractedField = ExtractedField()
    payment_method: ExtractedField = ExtractedField()


class ExtractionEnvelope(BaseModel):
    """Always a list: an invoice yields one record, a statement yields many."""

    records: list[ExtractedRecord] = Field(default_factory=list)


def json_schema() -> dict[str, Any]:
    return ExtractionEnvelope.model_json_schema()


def flatten(envelope: ExtractionEnvelope) -> tuple[list[dict], list[dict[str, float]]]:
    """Split the envelope into raw values and per-field confidence.

    The raw values are shaped exactly like a CSV row on purpose, so a PDF record
    enters the same pipeline as an imported one.
    """
    records: list[dict] = []
    confidences: list[dict[str, float]] = []
    for record in envelope.records:
        values, scores = {}, {}
        for name in EXTRACTION_FIELDS:
            extracted: ExtractedField = getattr(record, name)
            values[name] = extracted.value
            scores[name] = extracted.confidence
        records.append(values)
        confidences.append(scores)
    return records, confidences


def record_confidence(scores: dict[str, float]) -> float:
    """Aggregate to the MINIMUM confidence across required fields.

    A record is only as trustworthy as its least certain required field. A mean
    would drown one doubtful value among fourteen certain ones and let through
    as VALID a record a human should have read.
    """
    relevant = [scores.get(name, 0.0) for name in REQUIRED_FIELDS if name in scores]
    return min(relevant) if relevant else 0.0


EXTRACTION_PROMPT = f"""You extract financial records from a document into a fixed schema.

Rules, in order of importance:

1. NEVER invent a value. If the document does not state it, return null with
   confidence 0.0. A missing field is expected and handled; a guessed one is not.

2. How many records:
   - a supplier invoice produces exactly ONE record;
   - a bank statement produces ONE RECORD PER TRANSACTION LINE.

3. On a bank statement, take the per-line transaction Amount.
   NEVER take the running Balance column: it is the account total after the
   line, not the value of the line.

4. Amount mapping, which is the part most often got wrong:
   - gross_amount: the amount BEFORE tax and fees (an invoice subtotal);
   - tax_amount: VAT or other tax, 0 if none;
   - fee_amount: fees charged, 0 if none;
   - net_amount: the total actually payable or settled.
   For an invoice this means gross_amount is the subtotal, NOT the grand total.
   Keep the sign: money leaving the account is negative.

5. currency must be one of: {", ".join(c.value for c in Currency)}.

6. category must be exactly one of: {", ".join(c.value for c in Category)}.
   Choose OTHER rather than inventing a value.

7. payment_method, when stated, must be one of:
   {", ".join(p.value for p in PaymentMethod)}. Otherwise null.

8. country: ISO 3166-1 alpha-2 of the counterparty. On an invoice this is the
   supplier's country.

9. Dates as YYYY-MM-DD when the document allows it.

10. confidence is per field: how certain you are of THAT value. Use a low value
    when you inferred or reformatted rather than read it directly.
"""
