"""Invalid values must reach the database, not break the insert.

This is the premise of the whole application: a bad row becomes a NEEDS_REVIEW
record. Any schema constraint on a user-supplied column turns that reportable
error into a failed INSERT -- and because an import runs in one transaction, one
bad cell would lose the entire file.

SQLite silently ignores VARCHAR limits, so these cases could never fail here
before the columns were widened; they would only have surfaced on PostgreSQL.
"""

import pytest

from tests.conftest import make_csv, upload_csv
from tests.factories import make_raw


@pytest.mark.parametrize(
    ("field", "value", "expected_code"),
    [
        ("country", "LUX", "INVALID_COUNTRY_CODE"),
        ("country", "LUXEMBOURG", "INVALID_COUNTRY_CODE"),
        ("currency", "EUROS_PLEASE", "UNSUPPORTED_CURRENCY"),
        ("category", "A_VERY_LONG_UNSUPPORTED_CATEGORY_NAME" * 2, "UNSUPPORTED_CATEGORY"),
        ("payment_method", "SOME_UNKNOWN_METHOD", "UNSUPPORTED_PAYMENT_METHOD"),
        ("gross_amount", "9" * 20, "AMOUNT_OUT_OF_RANGE"),
        ("counterparty_name", "x" * 400, "VALUE_TOO_LONG"),
        ("reference", "R" * 400, "VALUE_TOO_LONG"),
    ],
)
def test_invalid_value_is_persisted_as_needs_review(
    client, batch, field, value, expected_code
):
    response = upload_csv(client, batch["id"], make_csv([make_raw(**{field: value})]))
    assert response.status_code == 201
    assert response.json()["imported"] == 1

    record = client.get(f"/api/batches/{batch['id']}/records").json()[0]
    assert record["status"] == "NEEDS_REVIEW"
    assert expected_code in [error["code"] for error in record["validation_errors"]]


def test_one_bad_row_does_not_lose_the_others(client, batch):
    """The requirement this protects: import all rows rather than reject the file."""
    rows = [
        make_raw(reference="OK-1"),
        make_raw(reference="BAD", country="LUXEMBOURG"),
        make_raw(reference="OK-2"),
    ]
    response = upload_csv(client, batch["id"], make_csv(rows))

    assert response.json()["by_status"] == {"VALID": 2, "NEEDS_REVIEW": 1}


def test_the_original_value_survives_in_the_record(client, batch):
    """Reporting a value invalid must not mean discarding it: the user corrects it."""
    upload_csv(client, batch["id"], make_csv([make_raw(country="LUXEMBOURG")]))

    record = client.get(f"/api/batches/{batch['id']}/records").json()[0]
    assert record["country"] == "LUXEMBOURG"


def test_an_invalid_value_can_be_corrected(client, batch):
    upload_csv(client, batch["id"], make_csv([make_raw(country="LUXEMBOURG")]))
    record = client.get(f"/api/batches/{batch['id']}/records").json()[0]

    response = client.patch(f"/api/records/{record['id']}", json={"country": "LU"})

    assert response.json()["status"] == "VALID"
    assert response.json()["country"] == "LU"
