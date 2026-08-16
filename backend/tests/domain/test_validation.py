from decimal import Decimal

import pytest

from app.domain.enums import RecordStatus
from app.domain.errors import ErrorCode
from app.domain.normalization import normalize_record
from app.domain.validation import derive_status, validate_record
from tests.factories import make_raw


def codes(raw, **kwargs) -> list[ErrorCode]:
    """Normalize then validate, returning error codes only (never messages)."""
    record, form_errors = normalize_record(raw)
    return [e.code for e in validate_record(record, form_errors, **kwargs)]


def fields(raw, **kwargs) -> list[str]:
    record, form_errors = normalize_record(raw)
    return [e.field for e in validate_record(record, form_errors, **kwargs)]


class TestValidRow:
    def test_no_error(self):
        assert codes(make_raw()) == []

    def test_status_is_valid(self):
        assert derive_status(codes(make_raw())) is RecordStatus.VALID


class TestRequiredFields:
    @pytest.mark.parametrize(
        "field",
        [
            "reference",
            "description",
            "gross_amount",
            "net_amount",
            "currency",
            "counterparty_name",
            "country",
            "category",
        ],
    )
    def test_empty_required_field(self, field):
        assert ErrorCode.REQUIRED_FIELD_MISSING in codes(make_raw(**{field: ""}))

    @pytest.mark.parametrize("field", ["value_date", "counterparty_account", "invoice_number"])
    def test_empty_optional_field(self, field):
        assert codes(make_raw(**{field: ""})) == []

    def test_empty_payment_method_is_valid(self):
        """Inverse trap in the sample CSV: TX-2026-0029. The field is optional."""
        assert codes(make_raw(payment_method="")) == []

    def test_unreadable_field_is_not_also_reported_as_missing(self):
        """A form error suppresses the 'required' check on the same field.

        Without this rule TX-2026-0016 would raise two errors instead of one.
        """
        result = codes(make_raw(transaction_date="2026-13-16"))
        assert result == [ErrorCode.INVALID_DATE]
        assert ErrorCode.REQUIRED_FIELD_MISSING not in result


class TestAmounts:
    def test_zero_gross(self):
        assert ErrorCode.ZERO_AMOUNT in codes(
            make_raw(gross_amount="0.00", tax_amount="0.00", net_amount="0.00")
        )

    @pytest.mark.parametrize("field", ["fee_amount", "tax_amount"])
    def test_negative_amount(self, field):
        assert ErrorCode.NEGATIVE_AMOUNT in codes(make_raw(**{field: "-25.00"}))

    def test_inconsistent_net(self):
        assert ErrorCode.NET_AMOUNT_MISMATCH in codes(make_raw(net_amount="999.00"))

    def test_net_within_tolerance(self):
        """Tolerance of 0.01: 1170.01 is accepted against an expected 1170.00."""
        assert codes(make_raw(net_amount="1170.01")) == []

    def test_net_outside_tolerance(self):
        assert ErrorCode.NET_AMOUNT_MISMATCH in codes(make_raw(net_amount="1170.02"))

    def test_absent_fee_and_tax_default_to_zero(self):
        assert codes(make_raw(fee_amount="", tax_amount="", net_amount="1000.00")) == []

    def test_no_mismatch_when_gross_is_missing(self):
        """Flagging an arithmetic inconsistency on absent data helps nobody."""
        result = codes(make_raw(gross_amount=""))
        assert result == [ErrorCode.REQUIRED_FIELD_MISSING]

    def test_cascade_across_different_fields_is_kept(self):
        """TX-2026-0027: negative fee AND inconsistent net. Both are reported."""
        result = codes(
            make_raw(gross_amount="800.00", fee_amount="-25.00",
                     tax_amount="136.00", net_amount="911.00")
        )
        assert result == [ErrorCode.NEGATIVE_AMOUNT, ErrorCode.NET_AMOUNT_MISMATCH]


class TestEnums:
    def test_unsupported_currency(self):
        assert ErrorCode.UNSUPPORTED_CURRENCY in codes(make_raw(currency="JPY"))

    @pytest.mark.parametrize("currency", ["EUR", "USD", "GBP", "CHF"])
    def test_supported_currencies(self, currency):
        assert codes(make_raw(currency=currency)) == []

    def test_unsupported_category(self):
        assert ErrorCode.UNSUPPORTED_CATEGORY in codes(make_raw(category="UNKNOWN_CATEGORY"))

    def test_unsupported_payment_method(self):
        assert ErrorCode.UNSUPPORTED_PAYMENT_METHOD in codes(make_raw(payment_method="BITCOIN"))


class TestCountry:
    def test_well_formed_but_nonexistent_code(self):
        """A ^[A-Z]{2}$ regex would accept XX; we check against the real ISO list."""
        assert ErrorCode.INVALID_COUNTRY_CODE in codes(make_raw(country="XX"))

    def test_valid_lowercase_code(self):
        assert codes(make_raw(country="lu")) == []


class TestUniqueness:
    def test_duplicate_reference(self):
        result = codes(make_raw(), existing_references=frozenset({"TX-TEST-0001"}))
        assert result == [ErrorCode.DUPLICATE_REFERENCE]

    def test_missing_reference_is_not_flagged_as_duplicate(self):
        result = codes(make_raw(reference=""), existing_references=frozenset({"TX-TEST-0001"}))
        assert result == [ErrorCode.REQUIRED_FIELD_MISSING]


class TestConfidence:
    def test_low_confidence(self):
        assert ErrorCode.LOW_CONFIDENCE in codes(make_raw(extraction_confidence="0.42"))

    def test_sufficient_confidence(self):
        assert codes(make_raw(extraction_confidence="0.95")) == []

    def test_threshold_is_configurable(self):
        raw = make_raw(extraction_confidence="0.80")
        assert codes(raw) == []
        assert ErrorCode.LOW_CONFIDENCE in codes(raw, confidence_threshold=Decimal("0.90"))


class TestStatusDerivation:
    def test_without_error(self):
        assert derive_status([]) is RecordStatus.VALID

    def test_with_error(self):
        assert derive_status(codes(make_raw(currency="JPY"))) is RecordStatus.NEEDS_REVIEW

    def test_validated_is_never_derived(self):
        """VALIDATED requires an explicit user action."""
        assert derive_status([]) is not RecordStatus.VALIDATED


class TestAllErrorsAtOnce:
    def test_no_rule_short_circuits_the_others(self):
        result = fields(make_raw(currency="JPY", country="", category="NOPE"))
        assert set(result) == {"currency", "country", "category"}
