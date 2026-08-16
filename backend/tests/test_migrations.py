"""Migrations must be correct on a database that already holds data.

Applying a migration to an empty database proves almost nothing: the risky part
is what happens to rows that are already there. This suite exists because the
`import_sequence` migration originally used a server default, which would have
given every pre-existing row the same position and silently disabled the
duplicate policy on any real database.
"""

import sqlite3
import uuid
from datetime import datetime, timedelta

import pytest
from alembic import command
from alembic.config import Config

from tests.conftest import BACKEND_ROOT

BEFORE_IMPORT_SEQUENCE = "05981b87a213"


def _config(url: str) -> Config:
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    config.set_main_option("sqlalchemy.url", url)
    return config


def _insert_legacy_rows(path: str, batches: dict[str, int]) -> None:
    """Populate the schema as it existed before import_sequence."""
    connection = sqlite3.connect(path)
    tenant_id = str(uuid.uuid4())
    connection.execute(
        "INSERT INTO tenant (id, name, created_at) VALUES (?, ?, ?)",
        (tenant_id, "T", datetime(2026, 1, 1).isoformat()),
    )
    for batch_name, row_count in batches.items():
        batch_id = str(uuid.uuid4())
        connection.execute(
            "INSERT INTO import_batch (id, name, tenant_id, created_at) VALUES (?, ?, ?, ?)",
            (batch_id, batch_name, tenant_id, datetime(2026, 1, 1).isoformat()),
        )
        for index in range(row_count):
            connection.execute(
                """INSERT INTO financial_record
                   (id, batch_id, reference, source_type, source_document_name,
                    status, validation_errors, raw_payload, created_at, updated_at)
                   VALUES (?, ?, ?, 'CSV', 'legacy.csv', 'VALID', '[]', '{}', ?, ?)""",
                (
                    str(uuid.uuid4()),
                    batch_id,
                    f"{batch_name}-REF",
                    (datetime(2026, 1, 1) + timedelta(minutes=index)).isoformat(),
                    datetime(2026, 1, 1).isoformat(),
                ),
            )
    connection.commit()
    connection.close()


@pytest.fixture
def legacy_database(tmp_path) -> str:
    path = tmp_path / "legacy.db"
    url = f"sqlite:///{path}"
    command.upgrade(_config(url), BEFORE_IMPORT_SEQUENCE)
    _insert_legacy_rows(str(path), {"batch-a": 3, "batch-b": 2})
    return url


def _sequences_by_batch(url: str) -> dict[str, list[int]]:
    connection = sqlite3.connect(url.removeprefix("sqlite:///"))
    rows = connection.execute(
        """SELECT b.name, r.import_sequence
           FROM financial_record r JOIN import_batch b ON b.id = r.batch_id
           ORDER BY b.name, r.import_sequence"""
    ).fetchall()
    connection.close()
    grouped: dict[str, list[int]] = {}
    for name, sequence in rows:
        grouped.setdefault(name, []).append(sequence)
    return grouped


def test_upgrade_succeeds_on_a_populated_database(legacy_database):
    command.upgrade(_config(legacy_database), "head")


def test_existing_rows_receive_distinct_positions_per_batch(legacy_database):
    """The defect this test exists for: every row landing on sequence 0.

    With a shared position no record has a predecessor, so `references_before`
    returns nothing and every duplicate in an existing database would quietly
    become valid on its next revalidation.
    """
    command.upgrade(_config(legacy_database), "head")

    sequences = _sequences_by_batch(legacy_database)
    assert sequences["batch-a"] == [0, 1, 2]
    assert sequences["batch-b"] == [0, 1]


def test_positions_restart_at_zero_for_each_batch(legacy_database):
    command.upgrade(_config(legacy_database), "head")

    for positions in _sequences_by_batch(legacy_database).values():
        assert positions[0] == 0
        assert positions == sorted(set(positions))


USER_SUPPLIED_TEXT_COLUMNS = [
    ("financial_record", "reference"),
    ("financial_record", "currency"),
    ("financial_record", "counterparty_name"),
    ("financial_record", "counterparty_account"),
    ("financial_record", "country"),
    ("financial_record", "category"),
    ("financial_record", "invoice_number"),
    ("financial_record", "payment_method"),
    ("financial_record", "description"),
    ("financial_record", "source_document_name"),
    ("extraction_job", "document_name"),
]


@pytest.mark.parametrize(("table", "column"), USER_SUPPLIED_TEXT_COLUMNS)
def test_user_supplied_columns_are_unbounded_after_migration(legacy_database, table, column):
    """Assert the SQL type itself, not merely the behaviour.

    Behavioural tests cannot prove this one: SQLite ignores VARCHAR limits, so
    an over-long value is accepted whether the column is TEXT or VARCHAR(2).
    Reading the declared type is the only check available here. Full proof needs
    PostgreSQL in CI.
    """
    command.upgrade(_config(legacy_database), "head")

    connection = sqlite3.connect(legacy_database.removeprefix("sqlite:///"))
    declared = {
        row[1]: row[2] for row in connection.execute(f"PRAGMA table_info({table})")
    }
    connection.close()

    assert declared[column] == "TEXT", (
        f"{table}.{column} is {declared[column]}; a bounded type would make "
        "PostgreSQL reject an invalid value and fail the whole import"
    )


def test_column_has_no_server_default(legacy_database):
    """A default would quietly assign 0 to a code path that forgot to allocate."""
    command.upgrade(_config(legacy_database), "head")

    connection = sqlite3.connect(legacy_database.removeprefix("sqlite:///"))
    column = next(
        row
        for row in connection.execute("PRAGMA table_info(financial_record)")
        if row[1] == "import_sequence"
    )
    connection.close()
    assert column[4] is None, "import_sequence must not carry a server default"
    assert column[3] == 1, "import_sequence must be NOT NULL"
