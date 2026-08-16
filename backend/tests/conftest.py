"""Test fixtures.

The schema is created by running the real Alembic migrations, not
`create_all()`. That way every test run also proves the migration works from an
empty database -- which is what makes the PostgreSQL portability claim
verifiable rather than merely asserted.
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
from sqlalchemy.orm import Session

from app.db import create_app_engine, get_session
from app.main import create_app
from app.models import ExtractionJob, FinancialRecord, ImportBatch, Tenant
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


@pytest.fixture
def client(engine: Engine) -> Iterator[TestClient]:
    app = create_app()

    def _session_override() -> Iterator[Session]:
        db_session = Session(engine)
        try:
            yield db_session
        finally:
            db_session.close()

    app.dependency_overrides[get_session] = _session_override
    with TestClient(app) as test_client:
        yield test_client


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
