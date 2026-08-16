"""Factory for valid records.

Each test overrides only the field it exercises. Without this, twenty fields
would be repeated in every test -- and fewer tests would get written.
"""

from typing import Any

VALID_RAW: dict[str, Any] = {
    "reference": "TX-TEST-0001",
    "transaction_date": "2026-07-01",
    "value_date": "2026-07-01",
    "description": "Test transaction",
    "gross_amount": "1000.00",
    "fee_amount": "0.00",
    "tax_amount": "170.00",
    "net_amount": "1170.00",
    "currency": "EUR",
    "counterparty_name": "Test Counterparty SA",
    "counterparty_account": "LU280019400644750000",
    "country": "LU",
    "category": "PROFESSIONAL_SERVICES",
    "invoice_number": "INV-TEST-1",
    "payment_method": "BANK_TRANSFER",
}


def make_raw(**overrides: Any) -> dict[str, Any]:
    """Return a valid raw row, with the given fields overridden."""
    raw = dict(VALID_RAW)
    raw.update(overrides)
    return raw
