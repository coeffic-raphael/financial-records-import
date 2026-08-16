"""Cross-tenant isolation, enumerated from the application itself.

The routes are DISCOVERED, not listed. A hand-written list only protects the
routes someone remembered to add to it, which is precisely the failure mode this
suite exists to prevent: a route added later without tenant scoping would leak
silently while the suite stayed green.

Every route carrying a resource id is called with an identifier belonging to
another tenant, and must answer 404.
"""

import pytest

from app.main import create_app
from app.models import ExtractionJob, FinancialRecord, ImportBatch, Tenant

FOREIGN_REFERENCE = "OTHER-TENANT-REF"
FOREIGN_DESCRIPTION = "Belongs to another tenant"

# Routes with no resource id in the path cannot address another tenant's data:
# they either create something or list what the caller owns.
ID_PARAMETERS = {"batch_id", "record_id"}


def _scoped_routes() -> list[tuple[str, str]]:
    """Every API route taking a resource id, read from the published OpenAPI.

    The schema is used rather than app.routes because it is what the application
    actually exposes, and because it stays flat regardless of how the framework
    represents included routers internally.
    """
    paths = create_app().openapi()["paths"]
    return sorted(
        (method.upper(), path)
        for path, operations in paths.items()
        if path.startswith("/api")
        and any("{" + name + "}" in path for name in ID_PARAMETERS)
        for method in operations
        if method.lower() in {"get", "post", "patch", "put", "delete"}
    )


SCOPED_ROUTES = _scoped_routes()


def test_the_matrix_is_not_empty():
    """Guard against the discovery silently finding nothing and passing."""
    assert len(SCOPED_ROUTES) >= 10, SCOPED_ROUTES


@pytest.fixture
def foreign(session) -> dict[str, str]:
    """A complete set of resources owned by a different tenant."""
    tenant = Tenant(name="Demo Tenant B")
    session.add(tenant)
    session.flush()

    batch = ImportBatch(name="Other tenant batch", tenant_id=tenant.id)
    session.add(batch)
    session.flush()

    record = FinancialRecord(
        batch_id=batch.id,
        import_sequence=0,
        reference=FOREIGN_REFERENCE,
        description=FOREIGN_DESCRIPTION,
        source_type="CSV",
        source_document_name="other.csv",
        status="VALID",
        validation_errors=[],
        raw_payload={"reference": FOREIGN_REFERENCE},
    )
    job = ExtractionJob(
        batch_id=batch.id, document_name="other.pdf", status="SUCCEEDED"
    )
    session.add_all([record, job])
    session.commit()
    return {"batch_id": batch.id, "record_id": record.id}


def _call(client, method: str, path: str, ids: dict[str, str]):
    for name, value in ids.items():
        path = path.replace("{" + name + "}", value)

    if method in {"POST", "PATCH"} and "uploads" not in path:
        return client.request(method, path, json={"description": "hijacked"})
    if "uploads/csv" in path:
        return client.post(path, files={"file": ("x.csv", b"reference\nA\n", "text/csv")})
    if "uploads/pdf" in path:
        return client.post(path, files=[("files", ("x.pdf", b"%PDF-1.4", "application/pdf"))])
    return client.request(method, path)


@pytest.mark.parametrize(("method", "path"), SCOPED_ROUTES)
def test_route_refuses_another_tenants_resource(client, foreign, method, path):
    response = _call(client, method, path, foreign)

    assert response.status_code == 404, f"{method} {path} answered {response.status_code}"


@pytest.mark.parametrize(("method", "path"), SCOPED_ROUTES)
def test_route_never_answers_403(client, foreign, method, path):
    """403 would confirm the resource exists, which leaks across tenants."""
    assert _call(client, method, path, foreign).status_code != 403


@pytest.mark.parametrize(("method", "path"), SCOPED_ROUTES)
def test_route_never_echoes_foreign_data(client, foreign, method, path):
    body = _call(client, method, path, foreign).text
    assert FOREIGN_REFERENCE not in body
    assert FOREIGN_DESCRIPTION not in body


def test_a_write_attempt_leaves_the_foreign_record_untouched(client, session, foreign):
    client.patch(f"/api/records/{foreign['record_id']}", json={"description": "hijacked"})
    session.expire_all()

    record = session.get(FinancialRecord, foreign["record_id"])
    assert record.description == FOREIGN_DESCRIPTION


def test_a_foreign_upload_creates_no_job(client, session, foreign):
    client.post(
        f"/api/batches/{foreign['batch_id']}/uploads/pdf",
        files=[("files", ("x.pdf", b"%PDF-1.4", "application/pdf"))],
    )
    session.expire_all()

    jobs = session.query(ExtractionJob).filter_by(batch_id=foreign["batch_id"]).all()
    assert len(jobs) == 1, "only the fixture's job must exist"
