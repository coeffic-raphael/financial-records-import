from datetime import date
from decimal import Decimal

import pytest

from app.domain.errors import ErrorCode
from app.domain.normalization import (
    normalize_amount,
    normalize_country,
    normalize_date,
    normalize_enum,
    normalize_record,
    normalize_text,
)
from tests.factories import make_raw


class TestNormalizeAmount:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("1250.50", Decimal("1250.50")),
            ("1,200.00", Decimal("1200.00")),   # US thousands separator
            ("1.200,00", Decimal("1200.00")),   # European thousands separator
            ("1,200", Decimal("1200")),         # rule 3b
            ("1,20", Decimal("1.20")),          # rule 3c
            ("1.000.000", Decimal("1000000")),  # rule 3a
            ("-145.00", Decimal("-145.00")),
            ("0.00", Decimal("0.00")),
            ("1 250.50", Decimal("1250.50")),   # space as separator
            ("", None),
            (None, None),
        ],
    )
    def test_readable(self, raw, expected):
        value, readable = normalize_amount(raw)
        assert readable is True
        assert value == expected

    @pytest.mark.parametrize("raw", ["abc", "12abc", "--5", "1.2.3,4,5"])
    def test_unreadable(self, raw):
        value, readable = normalize_amount(raw)
        assert readable is False
        assert value is None

    def test_never_uses_float(self):
        value, _ = normalize_amount("0.1")
        assert isinstance(value, Decimal)
        assert value + Decimal("0.2") == Decimal("0.3")  # false in float arithmetic


class TestNormalizeDate:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("2026-07-01", date(2026, 7, 1)),
            ("01/07/2026", date(2026, 7, 1)),
            ("18/07/2026", date(2026, 7, 18)),  # day > 12 confirms day-first
            ("", None),
            (None, None),
        ],
    )
    def test_readable(self, raw, expected):
        value, readable = normalize_date(raw)
        assert readable is True
        assert value == expected

    @pytest.mark.parametrize("raw", ["2026-13-16", "bad-date", "32/01/2026", "07/2026"])
    def test_unreadable(self, raw):
        value, readable = normalize_date(raw)
        assert readable is False
        assert value is None


class TestNormalizeText:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [("  ABC  ", "ABC"), ("", None), ("   ", None), (None, None)],
    )
    def test_trims_and_empties_become_none(self, raw, expected):
        assert normalize_text(raw) == expected


class TestNormalizeEnum:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("bank_transfer", "BANK_TRANSFER"),
            ("  Bank Transfer ", "BANK_TRANSFER"),
            ("direct-debit", "DIRECT_DEBIT"),
            ("", None),
        ],
    )
    def test_uppercases_and_underscores(self, raw, expected):
        assert normalize_enum(raw) == expected

    def test_does_not_check_membership(self):
        """Membership is a business rule, so it belongs to validation."""
        assert normalize_enum("unknown category") == "UNKNOWN_CATEGORY"


class TestNormalizeCountry:
    @pytest.mark.parametrize(("raw", "expected"), [("lu", "LU"), (" gb ", "GB"), ("", None)])
    def test_uppercases(self, raw, expected):
        assert normalize_country(raw) == expected


class TestNormalizeRecord:
    def test_valid_row_has_no_form_error(self):
        record, errors = normalize_record(make_raw())
        assert errors == []
        assert record.gross_amount == Decimal("1000.00")
        assert record.transaction_date == date(2026, 7, 1)

    def test_unreadable_date_yields_form_error(self):
        _, errors = normalize_record(make_raw(transaction_date="2026-13-16"))
        assert [e.code for e in errors] == [ErrorCode.INVALID_DATE]
        assert errors[0].field == "transaction_date"

    def test_unreadable_amount_yields_form_error(self):
        _, errors = normalize_record(make_raw(gross_amount="abc"))
        assert [e.code for e in errors] == [ErrorCode.NOT_NUMERIC]

    def test_unreadable_value_kept_in_raw_payload(self):
        """Nothing is silently overwritten: the offending data stays inspectable."""
        record, _ = normalize_record(make_raw(transaction_date="2026-13-16"))
        assert record.transaction_date is None
        assert record.raw_payload["transaction_date"] == "2026-13-16"

    def test_source_is_propagated(self):
        record, _ = normalize_record(make_raw(), source_type="CSV", source_document_name="a.csv")
        assert record.source_type == "CSV"
        assert record.source_document_name == "a.csv"
