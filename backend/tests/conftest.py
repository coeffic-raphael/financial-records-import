"""Test fixtures.

The schema is created by running the real Alembic migrations, not
`create_all()`. Every test run therefore also proves the migration applies to an
empty database.

This proves it for SQLite only. PostgreSQL portability stays a claim until a
PostgreSQL service runs the same migrations in CI.
"""

import csv
import io
import os
import secrets

# The test suite runs in mock mode: it must never build a real provider, and the
# startup check would otherwise refuse to boot without a key. Set before any
# module reads the settings.
os.environ["EXTRACTION_PROVIDER"] = "mock"
# Generated rather than written down. Nothing in the suite depends on its value,
# so a literal would only be a high-entropy string in the repository that a
# secret scanner is right to flag and a reader has to think about.
os.environ.setdefault("JWT_SECRET", secrets.token_urlsafe(32))
os.environ.setdefault("COOKIE_SECURE", "false")
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import Engine, delete
from sqlalchemy.orm import Session, sessionmaker

from app.api.deps import get_extraction_provider
from app.db import create_app_engine, get_session, get_session_factory
from app.main import create_app
from app.models import (
    ExtractionJob,
    FinancialRecord,
    ImportBatch,
    RefreshToken,
    Tenant,
    User,
)
from app.services.pdf_extraction import reset_semaphore
from tests.factories import VALID_RAW

BACKEND_ROOT = Path(__file__).parents[1]
SAMPLES = BACKEND_ROOT.parent / "samples"


@pytest.fixture(scope="session")
def database_url(tmp_path_factory: pytest.TempPathFactory) -> str:
    return f"sqlite:///{tmp_path_factory.mktemp('db') / 'test.db'}"


@pytest.fixture(scope="session")
def engine(database_url: str) -> Engine:
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    config.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(config, "head")
    return create_app_engine(database_url)


@pytest.fixture(autouse=True)
def isolated_semaphore() -> Iterator[None]:
    """Each test gets a fresh concurrency limiter."""
    reset_semaphore()
    yield
    reset_semaphore()


@pytest.fixture(autouse=True)
def clean_tables(engine: Engine) -> Iterator[None]:
    """Every test starts from an empty database, in dependency order."""
    yield
    with Session(engine) as session:
        for model in (FinancialRecord, ExtractionJob, ImportBatch, RefreshToken, User, Tenant):
            session.execute(delete(model))
        session.commit()


@pytest.fixture
def session(engine: Engine) -> Iterator[Session]:
    with Session(engine) as db_session:
        yield db_session


TEST_PASSWORD = "correct-horse-battery-staple"


OWNER_EMAIL = "owner@example.com"
OTHER_EMAIL = "intruder@example.com"


def authenticate(test_client: TestClient, email: str = OWNER_EMAIL) -> TestClient:
    """Attach a real bearer token to every subsequent request.

    The suite does NOT bypass authentication. Tests written before it existed
    keep passing because they now go through it for real, which makes them more
    faithful than they were, not less.

    Registers, or signs in when the account already exists, so that several
    clients in one test can share an identity -- a fixture creating a batch and
    another uploading into it must be the same tenant, or the isolation rules
    correctly refuse them.
    """
    credentials = {"email": email, "name": "Test Owner", "password": TEST_PASSWORD}
    response = test_client.post("/api/auth/register", json=credentials)
    if response.status_code == 409:
        response = test_client.post(
            "/api/auth/login", json={"email": email, "password": TEST_PASSWORD}
        )
    assert response.status_code in (200, 201), response.text

    test_client.headers["Authorization"] = f"Bearer {response.json()['access_token']}"
    return test_client


def _build_client(engine: Engine, provider=None) -> TestClient:
    app = create_app()

    def _session_override() -> Iterator[Session]:
        db_session = Session(engine)
        try:
            yield db_session
        finally:
            db_session.close()

    app.dependency_overrides[get_session] = _session_override
    # Background tasks open their own session; without this override they would
    # write to the development database instead of the test one.
    app.dependency_overrides[get_session_factory] = lambda: sessionmaker(
        bind=engine, autoflush=False, expire_on_commit=False
    )
    if provider is not None:
        app.dependency_overrides[get_extraction_provider] = lambda: provider
    return TestClient(app)


@pytest.fixture
def client(engine: Engine) -> Iterator[TestClient]:
    """An authenticated client, owning its own freshly created tenant."""
    with _build_client(engine) as test_client:
        yield authenticate(test_client, OWNER_EMAIL)


@pytest.fixture
def other_client(engine: Engine) -> Iterator[TestClient]:
    """A second, unrelated account -- the one isolation is tested against."""
    with _build_client(engine) as test_client:
        yield authenticate(test_client, OTHER_EMAIL)


@pytest.fixture
def anonymous_client(engine: Engine) -> Iterator[TestClient]:
    """No credentials at all."""
    with _build_client(engine) as test_client:
        yield test_client


@pytest.fixture
def client_with_provider(engine: Engine):
    """Build a client whose extraction provider is a double.

    No test ever reaches the network: the provider is substituted at the
    dependency, which is also how a different provider would be wired in
    production.
    """
    clients: list[TestClient] = []

    def _make(provider) -> TestClient:
        test_client = _build_client(engine, provider)
        test_client.__enter__()
        clients.append(test_client)
        # Same identity as the `client` fixture, so a batch created there is
        # reachable here: different accounts are correctly isolated.
        return authenticate(test_client, OWNER_EMAIL)

    yield _make
    for test_client in clients:
        test_client.__exit__(None, None, None)


@pytest.fixture
def batch(client: TestClient) -> dict:
    response = client.post("/api/batches", json={"name": "July 2026"})
    assert response.status_code == 201
    return response.json()


@pytest.fixture
def sample_csv() -> bytes:
    return (SAMPLES / "transactions_import.csv").read_bytes()


def upload_csv(client: TestClient, batch_id: str, content: bytes, name: str = "t.csv"):
    return client.post(
        f"/api/batches/{batch_id}/uploads/csv",
        files={"file": (name, content, "text/csv")},
    )


CSV_COLUMNS = list(VALID_RAW.keys())


def make_csv(rows: list[dict], columns: list[str] | None = None) -> bytes:
    """Build a small CSV for focused cases.

    The 30-row sample stays the oracle; these are for single-rule scenarios.
    """
    buffer = io.StringIO()
    fieldnames = columns if columns is not None else CSV_COLUMNS
    writer = csv.DictWriter(buffer, fieldnames=fieldnames)
    writer.writeheader()
    for row in rows:
        writer.writerow({name: row.get(name, "") for name in fieldnames})
    return buffer.getvalue().encode("utf-8")
