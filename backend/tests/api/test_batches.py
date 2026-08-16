"""Batch endpoints and tenant scoping."""


from app.models import ImportBatch, Tenant
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


# Cross-tenant coverage lives in test_tenant_isolation.py, where the routes are
# discovered from the application instead of being listed by hand.


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
