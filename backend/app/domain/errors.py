"""Field-level validation errors.

`code` is machine-readable: it is what the frontend uses to attach an error to
the right form field. `message` targets humans and may change without breaking
tests, which assert on codes only.
"""

from dataclasses import dataclass
from enum import StrEnum


class ErrorCode(StrEnum):
    REQUIRED_FIELD_MISSING = "REQUIRED_FIELD_MISSING"
    DUPLICATE_REFERENCE = "DUPLICATE_REFERENCE"
    INVALID_DATE = "INVALID_DATE"
    NOT_NUMERIC = "NOT_NUMERIC"
    ZERO_AMOUNT = "ZERO_AMOUNT"
    NEGATIVE_AMOUNT = "NEGATIVE_AMOUNT"
    NET_AMOUNT_MISMATCH = "NET_AMOUNT_MISMATCH"
    UNSUPPORTED_CURRENCY = "UNSUPPORTED_CURRENCY"
    INVALID_COUNTRY_CODE = "INVALID_COUNTRY_CODE"
    UNSUPPORTED_CATEGORY = "UNSUPPORTED_CATEGORY"
    UNSUPPORTED_PAYMENT_METHOD = "UNSUPPORTED_PAYMENT_METHOD"
    LOW_CONFIDENCE = "LOW_CONFIDENCE"


@dataclass(frozen=True, slots=True)
class FieldError:
    field: str
    code: ErrorCode
    message: str

    def as_dict(self) -> dict[str, str]:
        return {"field": self.field, "code": self.code.value, "message": self.message}
