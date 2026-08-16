"""Enumerations of the common `financial_record` model.

Values come verbatim from the data dictionary. They are used for *membership
testing*, not for coercion: an unsupported value must be persistable as
NEEDS_REVIEW rather than raising.
"""

from enum import StrEnum


class Currency(StrEnum):
    EUR = "EUR"
    USD = "USD"
    GBP = "GBP"
    CHF = "CHF"


class Category(StrEnum):
    MANAGEMENT_FEE = "MANAGEMENT_FEE"
    BANK_FEE = "BANK_FEE"
    PROFESSIONAL_SERVICES = "PROFESSIONAL_SERVICES"
    SUBSCRIPTION = "SUBSCRIPTION"
    SOFTWARE = "SOFTWARE"
    AUDIT = "AUDIT"
    INTEREST_PAYMENT = "INTEREST_PAYMENT"
    EXPENSE_REIMBURSEMENT = "EXPENSE_REIMBURSEMENT"
    REGULATORY_FEE = "REGULATORY_FEE"
    REDEMPTION = "REDEMPTION"
    CORPORATE_SERVICES = "CORPORATE_SERVICES"
    FX_ADJUSTMENT = "FX_ADJUSTMENT"
    INSURANCE = "INSURANCE"
    ADMINISTRATION_FEE = "ADMINISTRATION_FEE"
    OTHER = "OTHER"


class PaymentMethod(StrEnum):
    BANK_TRANSFER = "BANK_TRANSFER"
    DIRECT_DEBIT = "DIRECT_DEBIT"
    CARD = "CARD"
    INTERNAL = "INTERNAL"


class RecordStatus(StrEnum):
    """Fixed to three values by the data dictionary.

    PROCESSING deliberately does NOT belong here: the state of an extraction
    lives on `extraction_job`, not on the record. Adding a technical state would
    break conformance with the common model.
    """

    NEEDS_REVIEW = "NEEDS_REVIEW"
    VALID = "VALID"
    VALIDATED = "VALIDATED"


class SourceType(StrEnum):
    CSV = "CSV"
    PDF = "PDF"


class JobStatus(StrEnum):
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
