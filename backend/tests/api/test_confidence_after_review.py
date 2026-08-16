"""A human correction changes what the confidence describes.

Extraction confidence measures THE EXTRACTION, not the data as it stands. Left
untouched by corrections it made the workflow a dead end: a record the model
could not complete kept LOW_CONFIDENCE forever, so filling in every missing
field still left it NEEDS_REVIEW and it could never be approved -- exactly the
records that most needed reviewing.
"""

import pytest

from app.providers.mock import MockProvider

PDF = b"%PDF-1.4"


def _record(**overrides):
    record = {
        "reference": "STM-7711",
        "transaction_date": "2026-07-01",
        "description": "Subscription proceeds",
        "gross_amount": None,
        "fee_amount": "0.00",
        "tax_amount": "0.00",
        "net_amount": "75000.00",
        "currency": "EUR",
        "counterparty_name": None,
        "country": None,
        "category": "SUBSCRIPTION",
    }
    record.update(overrides)
    return record


def _scores(**overrides):
    scores = dict.fromkeys(_record(), 0.95)
    scores.update({"gross_amount": 0.0, "counterparty_name": 0.0, "country": 0.0})
    scores.update(overrides)
    return scores


@pytest.fixture
def extracted(client_with_provider, batch):
    """One PDF record the model could not complete, as the statement produces."""
    client = client_with_provider(
        MockProvider(records=[_record()], field_confidence=[_scores()])
    )
    client.post(
        f"/api/batches/{batch['id']}/uploads/pdf",
        files=[("files", ("statement.pdf", PDF, "application/pdf"))],
    )
    record = client.get(f"/api/batches/{batch['id']}/records").json()[0]
    return client, record


class TestBeforeAnyReview:
    def test_the_record_needs_review(self, extracted):
        _, record = extracted
        assert record["status"] == "NEEDS_REVIEW"
        assert record["extraction_confidence"] == "0.00"

    def test_low_confidence_is_reported(self, extracted):
        _, record = extracted
        assert "LOW_CONFIDENCE" in [e["code"] for e in record["validation_errors"]]


class TestAfterCorrection:
    def test_filling_the_missing_fields_clears_every_issue(self, extracted):
        client, record = extracted

        response = client.patch(
            f"/api/records/{record['id']}",
            json={
                "gross_amount": "75000.00",
                "counterparty_name": "Helvetia Holdings AG",
                "country": "CH",
            },
        )

        assert response.json()["validation_errors"] == []
        assert response.json()["status"] == "VALID"

    def test_the_aggregate_rises_to_what_remains_model_sourced(self, extracted):
        client, record = extracted

        response = client.patch(
            f"/api/records/{record['id']}",
            json={
                "gross_amount": "75000.00",
                "counterparty_name": "Helvetia Holdings AG",
                "country": "CH",
            },
        )

        # The three corrected fields are certain; 0.95 is the lowest of the rest.
        assert response.json()["extraction_confidence"] == "0.95"

    def test_corrected_fields_are_marked_certain(self, extracted):
        client, record = extracted

        response = client.patch(
            f"/api/records/{record['id']}", json={"counterparty_name": "Helvetia Holdings AG"}
        )

        assert response.json()["field_confidence"]["counterparty_name"] == 1.0

    def test_the_record_can_then_be_approved(self, extracted):
        client, record = extracted
        client.patch(
            f"/api/records/{record['id']}",
            json={
                "gross_amount": "75000.00",
                "counterparty_name": "Helvetia Holdings AG",
                "country": "CH",
            },
        )

        response = client.post(f"/api/records/{record['id']}/validate")

        assert response.status_code == 200
        assert response.json()["status"] == "VALIDATED"


class TestWhatCorrectionDoesNotExcuse:
    def test_an_untouched_uncertain_field_still_blocks(self, client_with_provider, batch):
        """Reviewing one field is not reviewing the record.

        A value the model was unsure about and nobody looked at must keep the
        record out of approval; otherwise any edit would wave everything through.
        """
        scores = _scores(description=0.2)
        client = client_with_provider(
            MockProvider(records=[_record()], field_confidence=[scores])
        )
        client.post(
            f"/api/batches/{batch['id']}/uploads/pdf",
            files=[("files", ("statement.pdf", PDF, "application/pdf"))],
        )
        record = client.get(f"/api/batches/{batch['id']}/records").json()[0]

        response = client.patch(
            f"/api/records/{record['id']}",
            json={
                "gross_amount": "75000.00",
                "counterparty_name": "Helvetia Holdings AG",
                "country": "CH",
            },
        )

        assert response.json()["extraction_confidence"] == "0.20"
        assert [e["code"] for e in response.json()["validation_errors"]] == ["LOW_CONFIDENCE"]
        assert response.json()["status"] == "NEEDS_REVIEW"

    def test_a_csv_record_is_unaffected(self, client, batch):
        """CSV rows carry no extraction confidence to adjust."""
        from tests.conftest import make_csv, upload_csv
        from tests.factories import make_raw

        upload_csv(client, batch["id"], make_csv([make_raw(currency="JPY")]))
        record = client.get(f"/api/batches/{batch['id']}/records").json()[0]

        response = client.patch(f"/api/records/{record['id']}", json={"currency": "EUR"})

        assert response.json()["extraction_confidence"] is None
        assert response.json()["status"] == "VALID"
