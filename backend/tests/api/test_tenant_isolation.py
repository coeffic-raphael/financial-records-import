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
from app.models import FinancialRecord
from tests.conftest import make_csv
from tests.factories import VALID_RAW

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
def foreign(other_client) -> dict[str, str]:
    """Resources belonging to a DIFFERENT real account.

    Created through the API by a second authenticated user rather than inserted
    into the database, so what is exercised is the real scenario: two people
    signed in at the same time, one reaching for the other's data.
    """
    batch_id = other_client.post("/api/batches", json={"name": "Other workspace"}).json()["id"]
    other_client.post(
        f"/api/batches/{batch_id}/uploads/csv",
        files={"file": ("other.csv", _foreign_csv(), "text/csv")},
    )
    record_id = other_client.get(f"/api/batches/{batch_id}/records").json()["items"][0]["id"]
    return {"batch_id": batch_id, "record_id": record_id}


def _foreign_csv() -> bytes:
    row = dict(VALID_RAW)
    row["reference"] = FOREIGN_REFERENCE
    row["description"] = FOREIGN_DESCRIPTION
    return make_csv([row])


def _call(client, method: str, path: str, ids: dict[str, str]):
    for name, value in ids.items():
        path = path.replace("{" + name + "}", value)

    # A body valid for THIS route, or FastAPI answers 422 from schema validation
    # before the tenant check ever runs and the route is never really probed.
    # (422 would not leak anything -- it depends only on the body -- but it
    # would quietly stop testing what this matrix exists for.)
    if method == "PATCH" and path.endswith("/records"):
        return client.request(
            method,
            path,
            json={"record_ids": [ids["record_id"]], "changes": {"description": "hijacked"}},
        )
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


def test_an_anonymous_caller_is_refused_everywhere(anonymous_client, foreign):
    """Without a token there is no tenant at all, so nothing is reachable."""
    for method, path in SCOPED_ROUTES:
        response = _call(anonymous_client, method, path, foreign)
        assert response.status_code == 401, f"{method} {path} answered {response.status_code}"


def test_the_owner_can_reach_their_own_resources(other_client, foreign):
    """The counterpart: isolation must not be achieved by refusing everyone."""
    response = other_client.get(f"/api/batches/{foreign['batch_id']}")
    assert response.status_code == 200
    assert FOREIGN_REFERENCE in other_client.get(
        f"/api/batches/{foreign['batch_id']}/records"
    ).text
