"""PDF extraction through the API, with the provider substituted by a double.

No test here touches the network. The provider is replaced at the dependency,
which is the same seam a different provider would be wired through in
production.
"""

import pytest

from app.providers.base import (
    InvalidProviderResponseError,
    PermanentProviderError,
    TransientProviderError,
)
from app.providers.mock import MockProvider

PDF = b"%PDF-1.4 fake bytes"


def _upload(client, batch_id, names=("invoice.pdf",)):
    files = [("files", (name, PDF, "application/pdf")) for name in names]
    return client.post(f"/api/batches/{batch_id}/uploads/pdf", files=files)


def _invoice_record(**overrides):
    record = {
        "reference": "INV-LX-441",
        "transaction_date": "2026-07-02",
        "value_date": "2026-07-17",
        "description": "Legal structuring services",
        "gross_amount": "3900.00",
        "fee_amount": "0.00",
        "tax_amount": "780.00",
        "net_amount": "4680.00",
        "currency": "EUR",
        "counterparty_name": "LexBridge Advisory S.A.",
        "counterparty_account": "LU55 0019 8000 4411 2200",
        "country": "LU",
        "category": "PROFESSIONAL_SERVICES",
        "invoice_number": "INV-LX-441",
        "payment_method": "BANK_TRANSFER",
    }
    record.update(overrides)
    return record


# The eight lines of the supplied statement, with the Amount column -- never the
# running Balance.
STATEMENT_AMOUNTS = [
    "75000.00",
    "-250.00",
    "-4680.00",
    "1245.35",
    "-50000.00",
    "-5616.00",
    "-35.00",
    "8750.00",
]
STATEMENT_BALANCES = {
    "323500.00",
    "323250.00",
    "318570.00",
    "319815.35",
    "269815.35",
    "264199.35",
    "264164.35",
    "272914.35",
}


def _statement_records():
    return [
        {
            "reference": f"STM-77{11 + index}",
            "transaction_date": "2026-07-01",
            "description": f"Statement line {index}",
            "gross_amount": amount,
            "fee_amount": "0.00",
            "tax_amount": "0.00",
            "net_amount": amount,
            "currency": "EUR",
            "counterparty_name": "Northbridge Fund SCSp",
            "country": "LU",
            "category": "OTHER",
        }
        for index, amount in enumerate(STATEMENT_AMOUNTS)
    ]


class TestUploadIsNotBlocking:
    def test_returns_202_with_jobs(self, client_with_provider, batch):
        client = client_with_provider(MockProvider(records=[_invoice_record()]))
        response = _upload(client, batch["id"])

        assert response.status_code == 202
        assert len(response.json()["jobs"]) == 1

    def test_one_job_per_file(self, client_with_provider, batch):
        client = client_with_provider(MockProvider(records=[_invoice_record()]))
        response = _upload(client, batch["id"], ("a.pdf", "b.pdf", "c.pdf"))

        assert len(response.json()["jobs"]) == 3
        assert len(client.get(f"/api/batches/{batch['id']}/jobs").json()) == 3

    def test_job_reaches_succeeded(self, client_with_provider, batch):
        client = client_with_provider(MockProvider(records=[_invoice_record()]))
        _upload(client, batch["id"])

        job = client.get(f"/api/batches/{batch['id']}/jobs").json()[0]
        assert job["status"] == "SUCCEEDED"
        assert job["record_count"] == 1

    def test_processing_never_leaks_into_record_status(self, client_with_provider, batch):
        """The data dictionary fixes record status to three values.

        Extraction state belongs to the job; putting it on the record would
        break conformance with the common model.
        """
        client = client_with_provider(MockProvider(records=[_invoice_record()]))
        _upload(client, batch["id"])

        page = client.get(f"/api/batches/{batch['id']}/records").json()
        statuses = {record["status"] for record in page["items"]}
        assert statuses <= {"NEEDS_REVIEW", "VALID", "VALIDATED"}


class TestInvoiceExtraction:
    def test_one_invoice_yields_one_record(self, client_with_provider, batch):
        client = client_with_provider(MockProvider(records=[_invoice_record()]))
        _upload(client, batch["id"])

        records = client.get(f"/api/batches/{batch['id']}/records").json()["items"]
        assert len(records) == 1
        assert records[0]["source_type"] == "PDF"
        assert records[0]["status"] == "VALID"

    def test_extracted_records_go_through_the_same_validation(self, client_with_provider, batch):
        """No PDF-specific validation exists: an unsupported currency is caught
        by the very rule that catches it in a CSV."""
        client = client_with_provider(MockProvider(records=[_invoice_record(currency="JPY")]))
        _upload(client, batch["id"])

        record = client.get(f"/api/batches/{batch['id']}/records").json()["items"][0]
        assert [e["code"] for e in record["validation_errors"]] == ["UNSUPPORTED_CURRENCY"]

    def test_original_filename_is_preserved(self, client_with_provider, batch):
        client = client_with_provider(MockProvider(records=[_invoice_record()]))
        _upload(client, batch["id"], ("invoice_legal_services.pdf",))

        record = client.get(f"/api/batches/{batch['id']}/records").json()["items"][0]
        assert record["source_document_name"] == "invoice_legal_services.pdf"


class TestBankStatement:
    def test_produces_one_record_per_line(self, client_with_provider, batch):
        client = client_with_provider(MockProvider(records=_statement_records()))
        _upload(client, batch["id"], ("bank_statement_july_2026.pdf",))

        records = client.get(f"/api/batches/{batch['id']}/records").json()["items"]
        assert len(records) == 8

    def test_amounts_are_transaction_values_not_running_balances(self, client_with_provider, batch):
        """The trap of the supplied statement: two adjacent numeric columns."""
        client = client_with_provider(MockProvider(records=_statement_records()))
        _upload(client, batch["id"])

        amounts = {
            r["net_amount"]
            for r in client.get(f"/api/batches/{batch['id']}/records").json()["items"]
        }
        assert amounts == set(STATEMENT_AMOUNTS)
        assert not amounts & STATEMENT_BALANCES


class TestIncompleteExtraction:
    def test_missing_required_fields_are_saved_as_needs_review(self, client_with_provider, batch):
        """Explicit assignment requirement: saved, not discarded."""
        client = client_with_provider(
            MockProvider(records=[{"reference": "PARTIAL-1", "description": "Only two fields"}])
        )
        _upload(client, batch["id"])

        records = client.get(f"/api/batches/{batch['id']}/records").json()["items"]
        assert len(records) == 1
        assert records[0]["status"] == "NEEDS_REVIEW"
        assert "REQUIRED_FIELD_MISSING" in [e["code"] for e in records[0]["validation_errors"]]

    def test_a_partial_batch_keeps_the_usable_records(self, client_with_provider, batch):
        client = client_with_provider(
            MockProvider(records=[_invoice_record(), {"reference": "BROKEN"}])
        )
        _upload(client, batch["id"])

        statuses = [
            r["status"] for r in client.get(f"/api/batches/{batch['id']}/records").json()["items"]
        ]
        assert sorted(statuses) == ["NEEDS_REVIEW", "VALID"]

    def test_an_empty_extraction_succeeds_with_no_records(self, client_with_provider, batch):
        client = client_with_provider(MockProvider(records=[]))
        _upload(client, batch["id"])

        job = client.get(f"/api/batches/{batch['id']}/jobs").json()[0]
        assert job["status"] == "SUCCEEDED"
        assert job["record_count"] == 0


class TestLowConfidence:
    def test_low_confidence_forces_review_without_any_field_error(
        self, client_with_provider, batch
    ):
        record = _invoice_record()
        scores = dict.fromkeys(record, 1.0)
        scores["counterparty_name"] = 0.2

        client = client_with_provider(MockProvider(records=[record], field_confidence=[scores]))
        _upload(client, batch["id"])

        persisted = client.get(f"/api/batches/{batch['id']}/records").json()["items"][0]
        assert persisted["status"] == "NEEDS_REVIEW"
        assert [e["code"] for e in persisted["validation_errors"]] == ["LOW_CONFIDENCE"]

    def test_field_confidence_is_exposed(self, client_with_provider, batch):
        record = _invoice_record()
        scores = dict.fromkeys(record, 0.91)
        client = client_with_provider(MockProvider(records=[record], field_confidence=[scores]))
        _upload(client, batch["id"])

        persisted = client.get(f"/api/batches/{batch['id']}/records").json()["items"][0]
        assert persisted["field_confidence"]["reference"] == 0.91
        assert persisted["extraction_confidence"] == "0.91"

    def test_confidence_survives_a_correction(self, client_with_provider, batch):
        """Revalidation replays raw_payload, so the confidence must live there."""
        record = _invoice_record()
        scores = dict.fromkeys(record, 0.2)
        client = client_with_provider(MockProvider(records=[record], field_confidence=[scores]))
        _upload(client, batch["id"])
        persisted = client.get(f"/api/batches/{batch['id']}/records").json()["items"][0]

        after = client.patch(f"/api/records/{persisted['id']}", json={"description": "Edited"})

        assert after.json()["status"] == "NEEDS_REVIEW"
        assert [e["code"] for e in after.json()["validation_errors"]] == ["LOW_CONFIDENCE"]


class TestProviderFailures:
    """The application must never crash on a provider problem."""

    @pytest.mark.parametrize(
        "error",
        [
            TransientProviderError("timeout"),
            PermanentProviderError("invalid api key"),
            InvalidProviderResponseError("payload does not match the schema"),
        ],
    )
    def test_failure_becomes_a_failed_job(self, client_with_provider, batch, error):
        client = client_with_provider(MockProvider(raises=error))
        response = _upload(client, batch["id"])

        assert response.status_code == 202, "the upload itself still succeeds"

        job = client.get(f"/api/batches/{batch['id']}/jobs").json()[0]
        assert job["status"] == "FAILED"
        assert job["error"]

    def test_nothing_is_persisted_when_extraction_fails(self, client_with_provider, batch):
        client = client_with_provider(MockProvider(raises=InvalidProviderResponseError("bad json")))
        _upload(client, batch["id"])

        assert client.get(f"/api/batches/{batch['id']}/records").json()["items"] == []

    def test_the_api_stays_available_after_a_failure(self, client_with_provider, batch):
        client = client_with_provider(MockProvider(raises=TransientProviderError("boom")))
        _upload(client, batch["id"])

        assert client.get("/api/health").json() == {"status": "ok"}
        assert client.get(f"/api/batches/{batch['id']}/summary").status_code == 200

    def test_an_unexpected_exception_is_still_contained(self, client_with_provider, batch):
        """A provider raising outside the contract must not escape the task."""
        client = client_with_provider(MockProvider(raises=RuntimeError("unexpected")))
        _upload(client, batch["id"])

        job = client.get(f"/api/batches/{batch['id']}/jobs").json()[0]
        assert job["status"] == "FAILED"
        assert "Unexpected error" in job["error"]


class TestJobsAreTenantScoped:
    def test_jobs_of_another_tenant_return_404(self, client, session):
        from app.models import ImportBatch, Tenant

        tenant = Tenant(name="Demo Tenant B")
        session.add(tenant)
        session.flush()
        other = ImportBatch(name="Other", tenant_id=tenant.id)
        session.add(other)
        session.commit()

        assert client.get(f"/api/batches/{other.id}/jobs").status_code == 404
