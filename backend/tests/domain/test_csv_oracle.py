"""Oracle: the supplied CSV exercised against the domain.

`transactions_import.csv` is not a sample, it is a disguised test suite -- one
row per validation rule. This test checks the domain against the real data with
NO database and NO HTTP: the application importer belongs to a later stage, only
normalization and validation are exercised here.

It asserts the EXACT set of codes per reference, not just the counts: an engine
returning the right totals for the wrong reasons would fail.
"""

import csv
from pathlib import Path

import pytest

from app.domain.enums import RecordStatus
from app.domain.errors import ErrorCode
from app.domain.normalization import normalize_record
from app.domain.validation import derive_status, validate_record

CSV_PATH = Path(__file__).parents[3] / "samples" / "transactions_import.csv"

# Reference (in file order, so the duplicated row appears twice) -> expected codes.
EXPECTED: list[tuple[str, list[ErrorCode]]] = [
    ("TX-2026-0001", []),
    ("TX-2026-0002", []),
    ("TX-2026-0003", []),
    ("TX-2026-0004", []),
    ("TX-2026-0005", []),
    ("TX-2026-0006", []),
    ("TX-2026-0007", []),
    ("TX-2026-0008", []),
    ("TX-2026-0009", []),
    ("TX-2026-0010", []),
    ("TX-2026-0011", []),
    ("TX-2026-0012", []),
    ("TX-2026-0013", []),
    ("TX-2026-0014", []),
    ("TX-2026-0015", []),
    ("TX-2026-0016", [ErrorCode.INVALID_DATE]),            # 2026-13-16
    ("TX-2026-0017", [ErrorCode.INVALID_DATE]),            # value_date = bad-date
    ("TX-2026-0018", [ErrorCode.UNSUPPORTED_CURRENCY]),    # JPY
    ("TX-2026-0019", [ErrorCode.REQUIRED_FIELD_MISSING]),  # empty counterparty_name
    ("TX-2026-0020", [ErrorCode.ZERO_AMOUNT]),             # gross = 0
    ("TX-2026-0003", [ErrorCode.DUPLICATE_REFERENCE]),     # intentional duplicate
    ("", [ErrorCode.REQUIRED_FIELD_MISSING]),              # missing reference
    ("TX-2026-0023", [ErrorCode.NET_AMOUNT_MISMATCH]),     # 1000 != 1160
    ("TX-2026-0024", [ErrorCode.REQUIRED_FIELD_MISSING]),  # missing gross
    ("TX-2026-0025", [ErrorCode.UNSUPPORTED_CATEGORY]),    # UNKNOWN_CATEGORY
    ("TX-2026-0026", [ErrorCode.REQUIRED_FIELD_MISSING]),  # empty country
    ("TX-2026-0027", [ErrorCode.NEGATIVE_AMOUNT,           # negative fee AND
                      ErrorCode.NET_AMOUNT_MISMATCH]),     # inconsistent net
    ("TX-2026-0028", []),  # INVERSE TRAP: "1,200.00" normalizes -> VALID
    ("TX-2026-0029", []),  # INVERSE TRAP: empty payment_method, optional field
    ("TX-2026-0030", []),
]


def _run_import() -> list[tuple[str, list[ErrorCode], RecordStatus]]:
    """Replay the import row by row, accumulating references as they are seen.

    Uniqueness is evaluated in arrival order: the SECOND occurrence of
    TX-2026-0003 is the offending one, not the first.
    """
    results = []
    seen: set[str] = set()
    with CSV_PATH.open(encoding="utf-8") as handle:
        for raw in csv.DictReader(handle):
            record, form_errors = normalize_record(
                raw, source_type="CSV", source_document_name=CSV_PATH.name
            )
            errors = validate_record(record, form_errors, existing_references=frozenset(seen))
            if record.reference is not None:
                seen.add(record.reference)
            results.append((raw["reference"], [e.code for e in errors], derive_status(errors)))
    return results


@pytest.fixture(scope="module")
def imported():
    return _run_import()


def test_sample_file_is_present():
    assert CSV_PATH.exists(), f"Sample file not found: {CSV_PATH}"


def test_every_row_is_imported(imported):
    """The assignment requires importing all rows rather than rejecting the file."""
    assert len(imported) == 30


@pytest.mark.parametrize(("index", "expected"), list(enumerate(EXPECTED)))
def test_exact_codes_per_row(imported, index, expected):
    reference, expected_codes = expected
    actual_reference, actual_codes, _ = imported[index]
    assert actual_reference == reference
    assert actual_codes == expected_codes


def test_split_is_18_valid_12_needs_review(imported):
    statuses = [status for _, _, status in imported]
    assert statuses.count(RecordStatus.VALID) == 18
    assert statuses.count(RecordStatus.NEEDS_REVIEW) == 12


def test_import_never_produces_validated(imported):
    """VALIDATED requires an explicit action: an import never yields it."""
    assert all(status is not RecordStatus.VALIDATED for _, _, status in imported)


class TestInverseTraps:
    """The two rows an over-rejecting implementation would wrongly flag."""

    def test_malformed_amount_becomes_valid(self, imported):
        """TX-2026-0028: "1,200.00" is a FORM problem, not a substance one."""
        reference, errors, status = imported[27]
        assert reference == "TX-2026-0028"
        assert errors == []
        assert status is RecordStatus.VALID

    def test_empty_payment_method_stays_valid(self, imported):
        """TX-2026-0029: the field is optional per the data dictionary."""
        reference, errors, status = imported[28]
        assert reference == "TX-2026-0029"
        assert errors == []
        assert status is RecordStatus.VALID
