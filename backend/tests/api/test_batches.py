"""Batch endpoints and tenant scoping."""

import pytest

from app.models import FinancialRecord, ImportBatch, Tenant
from tests.conftest import upload_csv


class TestBatchCrud:
    def test_create(self, client):
        response = client.post("/api/batches", json={"name": "July 2026"})
        assert response.status_code == 201
        assert response.json()["name"] == "July 2026"

    def test_create_rejects_empty_name(self, client):
        assert client.post("/api/batches", json={"name": ""}).status_code == 422

    def test_create_rejects_unknown_fields(self, client):
        response = client.post("/api/batches", json={"name": "X", "tenant_id": "sneaky"})
        assert response.status_code == 422

    def test_list(self, client, batch):
        assert [b["id"] for b in client.get("/api/batches").json()] == [batch["id"]]

    def test_get(self, client, batch):
        assert client.get(f"/api/batches/{batch['id']}").json()["id"] == batch["id"]

    def test_get_unknown_id_is_404(self, client):
        assert client.get("/api/batches/does-not-exist").status_code == 404


class TestTenantIsolation:
    """A resource from another tenant must be indistinguishable from a missing one."""

    def _other_tenant_batch(self, session) -> ImportBatch:
        tenant = Tenant(name="Demo Tenant B")
        session.add(tenant)
        session.flush()
        batch = ImportBatch(name="Other tenant batch", tenant_id=tenant.id)
        session.add(batch)
        session.commit()
        return batch

    def test_other_tenant_batch_is_not_listed(self, client, session):
        self._other_tenant_batch(session)
        assert client.get("/api/batches").json() == []

    def test_other_tenant_batch_returns_404_not_403(self, client, session):
        """403 would confirm the resource exists: that is a cross-tenant leak."""
        other = self._other_tenant_batch(session)
        response = client.get(f"/api/batches/{other.id}")

        assert response.status_code == 404
        assert response.status_code != 403
        assert response.json()["code"] == "NOT_FOUND"

    def test_other_tenant_records_return_404(self, client, session):
        other = self._other_tenant_batch(session)
        assert client.get(f"/api/batches/{other.id}/records").status_code == 404

    def test_other_tenant_summary_returns_404(self, client, session):
        other = self._other_tenant_batch(session)
        assert client.get(f"/api/batches/{other.id}/summary").status_code == 404

    def test_cannot_upload_into_another_tenant_batch(self, client, session, sample_csv):
        other = self._other_tenant_batch(session)
        assert upload_csv(client, other.id, sample_csv).status_code == 404


class TestRecordRouteIsolation:
    """Every record route, parametrised over the list rather than one test each.

    The point is to protect the FUTURE: a route added later without tenant
    scoping makes this suite fail, instead of creating a silent leak. The
    router-level dependency guarantees the tenant is RESOLVED; it does not by
    itself guarantee each query is SCOPED. Only this matrix does.
    """

    @pytest.fixture
    def foreign_record(self, session) -> FinancialRecord:
        tenant = Tenant(name="Demo Tenant B")
        session.add(tenant)
        session.flush()
        batch = ImportBatch(name="Other tenant batch", tenant_id=tenant.id)
        session.add(batch)
        session.flush()
        record = FinancialRecord(
            batch_id=batch.id,
            import_sequence=0,
            source_type="CSV",
            source_document_name="other.csv",
            status="VALID",
            validation_errors=[],
            raw_payload={"reference": "OTHER-1"},
            reference="OTHER-1",
        )
        session.add(record)
        session.commit()
        return record

    @pytest.mark.parametrize(
        ("method", "suffix", "payload"),
        [
            ("get", "", None),
            ("get", "/validation-errors", None),
            ("patch", "", {"description": "hijacked"}),
            ("post", "/revalidate", None),
            ("post", "/validate", None),
        ],
    )
    def test_route_returns_404_for_another_tenant(
        self, client, foreign_record, method, suffix, payload
    ):
        url = f"/api/records/{foreign_record.id}{suffix}"
        response = getattr(client, method)(url, **({"json": payload} if payload else {}))

        assert response.status_code == 404, f"{method.upper()} {url} leaked"
        assert response.status_code != 403
        assert "OTHER-1" not in response.text

    def test_foreign_record_is_left_untouched(self, client, session, foreign_record):
        client.patch(f"/api/records/{foreign_record.id}", json={"description": "hijacked"})
        session.expire_all()
        assert session.get(FinancialRecord, foreign_record.id).description is None


class TestSummary:
    def test_counts(self, client, batch, sample_csv):
        upload_csv(client, batch["id"], sample_csv, "transactions_import.csv")
        summary = client.get(f"/api/batches/{batch['id']}/summary").json()

        assert summary["total_records"] == 30
        assert summary["by_status"] == {"VALID": 18, "NEEDS_REVIEW": 12}
        assert summary["by_source_type"] == {"CSV": 30}
        assert summary["documents"] == [
            {"source_document_name": "transactions_import.csv", "count": 30}
        ]

    def test_totals_are_grouped_by_currency(self, client, batch, sample_csv):
        """Adding EUR to USD would be accounting nonsense: one line per currency."""
        upload_csv(client, batch["id"], sample_csv)
        summary = client.get(f"/api/batches/{batch['id']}/summary").json()

        currencies = [total["currency"] for total in summary["totals_by_currency"]]
        assert currencies == sorted(currencies)
        assert set(currencies) <= {"EUR", "USD", "GBP", "CHF", "JPY"}
        assert all(isinstance(t["net_amount"], str) for t in summary["totals_by_currency"])

    def test_empty_batch(self, client, batch):
        summary = client.get(f"/api/batches/{batch['id']}/summary").json()
        assert summary["total_records"] == 0
        assert summary["totals_by_currency"] == []


class TestCaching:
    def test_api_responses_are_not_cached(self, client, batch):
        """A cached GET must never be replayed to the next user on this machine."""
        response = client.get(f"/api/batches/{batch['id']}")
        assert response.headers["cache-control"] == "no-store"
