"""Record lifecycle: correction, revalidation, approval."""

import pytest

from tests.conftest import make_csv, upload_csv
from tests.factories import make_raw


@pytest.fixture
def records(client, batch):
    """One VALID record and one NEEDS_REVIEW record (unsupported currency)."""

    def _load(rows):
        upload_csv(client, batch["id"], make_csv(rows))
        return client.get(f"/api/batches/{batch['id']}/records").json()

    return _load


@pytest.fixture
def valid_record(records):
    return records([make_raw()])[0]


@pytest.fixture
def invalid_record(records):
    return records([make_raw(currency="JPY")])[0]


class TestCorrection:
    def test_fixing_the_offending_field_makes_the_record_valid(self, client, invalid_record):
        assert invalid_record["status"] == "NEEDS_REVIEW"

        response = client.patch(
            f"/api/records/{invalid_record['id']}", json={"currency": "EUR"}
        )

        assert response.status_code == 200
        assert response.json()["status"] == "VALID"
        assert response.json()["validation_errors"] == []

    def test_correction_goes_through_normalization(self, client, valid_record):
        """raw_payload is the source of truth, so a correction is normalized too.

        The user may type a localized amount and have it accepted, exactly as an
        imported value would be.
        """
        response = client.patch(
            f"/api/records/{valid_record['id']}",
            json={"gross_amount": "1 200,00", "tax_amount": "0.00", "net_amount": "1200.00"},
        )

        assert response.status_code == 200
        assert response.json()["gross_amount"] == "1200.00"
        assert response.json()["status"] == "VALID"

    def test_correction_can_introduce_a_new_error(self, client, valid_record):
        response = client.patch(
            f"/api/records/{valid_record['id']}", json={"country": "XX"}
        )
        assert response.json()["status"] == "NEEDS_REVIEW"
        assert [e["code"] for e in response.json()["validation_errors"]] == [
            "INVALID_COUNTRY_CODE"
        ]

    def test_unknown_record_is_404(self, client):
        assert client.patch("/api/records/nope", json={"currency": "EUR"}).status_code == 404


class TestStatusIsNotWritable:
    """If status were patchable, a client could declare itself VALIDATED."""

    def test_sending_status_is_rejected(self, client, invalid_record):
        response = client.patch(
            f"/api/records/{invalid_record['id']}", json={"status": "VALIDATED"}
        )
        assert response.status_code == 422
        assert response.json()["code"] == "INVALID_REQUEST"

    def test_sending_validation_errors_is_rejected(self, client, invalid_record):
        response = client.patch(
            f"/api/records/{invalid_record['id']}", json={"validation_errors": []}
        )
        assert response.status_code == 422

    def test_record_keeps_its_computed_status(self, client, invalid_record):
        client.patch(f"/api/records/{invalid_record['id']}", json={"status": "VALIDATED"})
        assert client.get(f"/api/records/{invalid_record['id']}").json()["status"] == (
            "NEEDS_REVIEW"
        )


class TestRevalidation:
    def test_revalidating_a_valid_record_keeps_it_valid(self, client, valid_record):
        """A record must not find its own reference and flag itself a duplicate.

        This is why the uniqueness check excludes the record being revalidated.
        Without that exclusion, correction would be impossible.
        """
        response = client.post(f"/api/records/{valid_record['id']}/revalidate")

        assert response.status_code == 200
        assert response.json()["status"] == "VALID"
        assert response.json()["validation_errors"] == []

    def test_revalidation_is_idempotent(self, client, valid_record):
        for _ in range(3):
            response = client.post(f"/api/records/{valid_record['id']}/revalidate")
            assert response.json()["status"] == "VALID"

    def test_duplicate_stays_duplicate_after_revalidation(self, client, batch):
        upload_csv(client, batch["id"], make_csv([make_raw(), make_raw()]))
        second = client.get(f"/api/batches/{batch['id']}/records").json()[1]

        response = client.post(f"/api/records/{second['id']}/revalidate")
        assert [e["code"] for e in response.json()["validation_errors"]] == [
            "DUPLICATE_REFERENCE"
        ]

    def test_renaming_a_duplicate_resolves_it(self, client, batch):
        upload_csv(client, batch["id"], make_csv([make_raw(), make_raw()]))
        second = client.get(f"/api/batches/{batch['id']}/records").json()[1]

        response = client.patch(
            f"/api/records/{second['id']}", json={"reference": "TX-TEST-0002"}
        )
        assert response.json()["status"] == "VALID"


class TestApproval:
    def test_valid_record_can_be_validated(self, client, valid_record):
        response = client.post(f"/api/records/{valid_record['id']}/validate")
        assert response.status_code == 200
        assert response.json()["status"] == "VALIDATED"

    def test_needs_review_record_cannot_be_validated(self, client, invalid_record):
        response = client.post(f"/api/records/{invalid_record['id']}/validate")
        assert response.status_code == 409
        assert response.json()["code"] == "RECORD_NOT_VALID"

    def test_correcting_a_validated_record_revalidates_it(self, client, valid_record):
        """A corrected record can never stay VALIDATED without passing validation."""
        client.post(f"/api/records/{valid_record['id']}/validate")

        response = client.patch(
            f"/api/records/{valid_record['id']}", json={"currency": "JPY"}
        )
        assert response.json()["status"] == "NEEDS_REVIEW"

    def test_a_valid_correction_also_drops_validated(self, client, valid_record):
        """Even a harmless edit forces re-approval: the assignment requires it."""
        client.post(f"/api/records/{valid_record['id']}/validate")

        response = client.patch(
            f"/api/records/{valid_record['id']}", json={"description": "Renamed"}
        )
        assert response.json()["status"] == "VALID"
