"""What validation accepts must be what storage keeps.

The bug this file exists for: normalization accepted 0.0001, the domain declared
the record VALID because the gross amount was non-zero, and the column then
stored 0.00. The record asserted something about a value the database never
received.

The guard is an invariant rather than a list of symptoms: any amount the domain
accepts must survive a round trip through the column unchanged.

The round trip is a real one. An earlier version called `process_bind_param` and
`process_result_value` with a dialect object, which for PostgreSQL were both
pass-throughs -- the assertion reduced to `value == value`. This writes into a
`NUMERIC(18, 2)` column through psycopg and reads it back.
"""

from decimal import Decimal

import pytest
from sqlalchemy import Column, MetaData, Numeric, String, Table, insert, select

from app.domain.errors import ErrorCode
from app.domain.normalization import normalize_amount, normalize_confidence

ACCEPTED_AMOUNTS = [
    "0",
    "0.01",
    "-0.01",
    "1250.50",
    "1,200.00",
    "1.200,00",
    "-145.00",
    "9999999999999999.99",
    "-9999999999999999.99",
]


@pytest.fixture(scope="module")
def amount_column(engine):
    """A real NUMERIC(18, 2) column, created and dropped around the module."""
    metadata = MetaData()
    table = Table(
        "storage_invariant_probe",
        metadata,
        Column("label", String(64), primary_key=True),
        Column("amount", Numeric(18, 2)),
    )
    metadata.create_all(engine)
    yield engine, table
    metadata.drop_all(engine)


@pytest.mark.parametrize("raw", ACCEPTED_AMOUNTS)
def test_accepted_amount_survives_storage_unchanged(raw, amount_column):
    engine, table = amount_column
    value, problem = normalize_amount(raw)
    assert problem is None, f"{raw!r} should be accepted"

    with engine.begin() as connection:
        connection.execute(insert(table).values(label=raw, amount=value))
        restored = connection.execute(
            select(table.c.amount).where(table.c.label == raw)
        ).scalar_one()

    assert restored == value, f"{raw!r} changed on its way through storage"
    assert isinstance(restored, Decimal), "an amount came back as something other than Decimal"


class TestScaleIsReportedNotRounded:
    """Rounding money silently is worse than refusing it."""

    @pytest.mark.parametrize("raw", ["0.0001", "1.9999", "1,234.5678", "1234.567"])
    def test_more_than_two_decimals_is_rejected(self, raw):
        value, problem = normalize_amount(raw)
        assert problem is ErrorCode.AMOUNT_SCALE_EXCEEDED
        assert value is None

    def test_exactly_two_decimals_is_accepted(self):
        assert normalize_amount("1.99") == (Decimal("1.99"), None)

    def test_a_tiny_amount_is_never_silently_zeroed(self):
        """0.0001 must not become a VALID record holding 0.00."""
        value, problem = normalize_amount("0.0001")
        assert value is None
        assert problem is ErrorCode.AMOUNT_SCALE_EXCEEDED


class TestThousandsHeuristic:
    """A three-digit group is only a thousands group if what precedes it can be one."""

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("1,200", Decimal("1200")),
            ("12,345", Decimal("12345")),
            ("123,456", Decimal("123456")),
            ("1.000.000", Decimal("1000000")),
        ],
    )
    def test_read_as_thousands(self, raw, expected):
        assert normalize_amount(raw) == (expected, None)

    def test_leading_zero_is_not_a_thousands_group(self):
        """0.001 used to be read as 1: "0" cannot be a leading thousands group."""
        value, problem = normalize_amount("0.001")
        assert problem is ErrorCode.AMOUNT_SCALE_EXCEEDED
        assert value is None


class TestConfidenceIsQuantizedOnPurpose:
    """A confidence is an estimate, so rounding it loses nothing actionable.

    This is the deliberate exception to the rule above, and the asymmetry is the
    point: rounding money loses money.
    """

    def test_extra_precision_is_rounded(self):
        assert normalize_confidence("0.9512") == (Decimal("0.95"), None)

    def test_rounding_is_half_up(self):
        assert normalize_confidence("0.955") == (Decimal("0.96"), None)

    def test_out_of_range_value_is_kept_for_the_validation_layer(self):
        """Storage stays generous; the range is a business rule."""
        value, problem = normalize_confidence("1.01")
        assert problem is None
        assert value == Decimal("1.01")
