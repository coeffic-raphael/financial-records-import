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
   - a bank statement produces ONE RECORD PER TRANSACTION ROW.

3. A bank statement is a TABLE. Read it row by row:
   - each data row is one transaction and becomes exactly ONE record;
   - if the table holds 8 data rows, return 8 records -- not 1, not 2;
   - NEVER merge two rows into a single record;
   - NEVER put two cells in one field. Every field takes the value of ONE cell
     of ONE row. A date like "2026-07-0101/07/2026" is two cells concatenated
     and is always wrong.

4. Typical statement columns map like this:
   - booking date column       -> transaction_date
   - value date column         -> value_date
   - reference column          -> reference
   - description column        -> description
   - per-row amount column     -> net_amount, keeping its sign
   - running Balance column    -> IGNORE it entirely. It is the account total
     after the row, not the value of the row.

   gross_amount, tax_amount and fee_amount are NULL on a statement row unless
   that row states them itself. A row shows what was settled, not how it was
   composed: writing gross = net asserts there was no tax, which the document
   never says. Rule 1 applies -- an absent breakdown is expected and handled,
   a guessed one is not.

5. A statement header describes the ACCOUNT, not the counterparty.

   "Account holder: X" is the owner of the account -- one side of every
   transaction. The counterparty is the OTHER side, so X is never it, and the
   account's own IBAN is not the counterparty's account. If a row does not name
   the other party, counterparty_name and counterparty_account are null.

   What a header DOES supply to every row:
   - the currency, when the rows do not repeat it;
   - country, from the account's own IBAN. The data dictionary names this field
     `country`, not `counterparty_country`, and defines it as "ISO alpha-2
     country code" without saying whose -- unlike the two fields above, which
     carry the counterparty prefix and its meaning with it.

6. Amount mapping, which is the part most often got wrong:
   - gross_amount: the amount BEFORE tax and fees (an invoice subtotal);
   - tax_amount: VAT or other tax, 0 if none;
   - fee_amount: fees charged, 0 if none;
   - net_amount: the total actually payable or settled.
   For an invoice this means gross_amount is the subtotal, NOT the grand total.
   Keep the sign: money leaving the account is negative.

7. currency must be one of: {", ".join(c.value for c in Currency)}.

8. category must be exactly one of: {", ".join(c.value for c in Category)}.
   Choose OTHER rather than inventing a value.

9. payment_method, when stated, must be one of:
   {", ".join(p.value for p in PaymentMethod)}. Otherwise null.

10. country: ISO 3166-1 alpha-2. On an invoice this is the supplier's country;
   on a statement it is the account's, per rule 5.

11. Dates as YYYY-MM-DD when the document allows it.

12. confidence is per field: how certain you are of THAT value. Use a low value
    when you inferred or reformatted rather than read it directly.
"""
