"""Normalized record -- pure domain object.

This is a `dataclass`, NOT a Pydantic model: Pydantic *raises* on a
non-conforming value, which is exactly the behaviour to avoid here since we
report errors ourselves and must persist the offending data. Pydantic stays at
the boundaries (API DTOs, provider output).

Enum-backed fields are typed `str | None` rather than `Currency | None`: an
unsupported value must survive normalization so it can be reported and then
corrected. This also matches the chosen storage (VARCHAR + CHECK).
"""

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any


@dataclass(frozen=True, slots=True)
class NormalizedRecord:
    reference: str | None = None
    transaction_date: date | None = None
    value_date: date | None = None
    description: str | None = None
    gross_amount: Decimal | None = None
    fee_amount: Decimal | None = None
    tax_amount: Decimal | None = None
    net_amount: Decimal | None = None
    currency: str | None = None
    counterparty_name: str | None = None
    counterparty_account: str | None = None
    country: str | None = None
    category: str | None = None
    invoice_number: str | None = None
    payment_method: str | None = None

    source_type: str | None = None
    source_document_name: str | None = None
    extraction_confidence: Decimal | None = None

    raw_payload: dict[str, Any] = field(default_factory=dict)
