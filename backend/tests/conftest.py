"""Test fixtures.

The schema is created by running the real Alembic migrations, not
`create_all()`. Every test run therefore also proves the migration applies to an
empty database.

This proves it for SQLite only. PostgreSQL portability stays a claim until a
PostgreSQL service runs the same migrations in CI.
"""

import csv
import io
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
from app.models import ExtractionJob, FinancialRecord, ImportBatch, Tenant
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
        for model in (FinancialRecord, ExtractionJob, ImportBatch, Tenant):
            session.execute(delete(model))
        session.commit()


@pytest.fixture
def session(engine: Engine) -> Iterator[Session]:
    with Session(engine) as db_session:
        yield db_session


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
        return test_client

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
