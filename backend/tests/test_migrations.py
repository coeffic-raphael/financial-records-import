"""Migrations must be correct on a database that already holds data.

Applying a migration to an empty database proves almost nothing: the risky part
is what happens to rows that are already there. This suite exists because the
`import_sequence` migration originally used a server default, which would have
given every pre-existing row the same position and silently disabled the
duplicate policy on any real database.

Each test gets its own PostgreSQL **schema**, not the shared test database.
That is not a convenience: these tests stop at old revisions, provoke failed
upgrades, and inspect a schema that does not yet have the `user` table -- none
of which can coexist with a database the rest of the suite expects at `head`.
"""

import uuid
from datetime import datetime, timedelta

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text

from tests.conftest import BACKEND_ROOT, TEST_DATABASE_URL

BEFORE_IMPORT_SEQUENCE = "05981b87a213"


def _config(url: str) -> Config:
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    # Alembic stores options in a configparser, which reads `%` as the start of
    # an interpolation. The search_path option below is percent-encoded, so the
    # sign has to be doubled here -- and only here: SQLAlchemy wants it single.
    config.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    return config


def _schema_url(schema: str) -> str:
    """The URL Alembic and every read below use.

    `search_path` travels in the URL rather than a `SET` statement: a SET only
    affects the connection that issued it, and Alembic opens its own.
    """
    separator = "&" if "?" in TEST_DATABASE_URL else "?"
    return f"{TEST_DATABASE_URL}{separator}options=-csearch_path%3D{schema}"


@pytest.fixture
def migration_schema():
    """A disposable schema, created and dropped through an admin connection.

    The admin connection deliberately carries no `search_path`: a schema cannot
    be created or dropped from inside itself.
    """
    schema = f"migration_test_{uuid.uuid4().hex}"
    admin = create_engine(TEST_DATABASE_URL, future=True)
    with admin.begin() as connection:
        connection.execute(text(f"CREATE SCHEMA {schema}"))
    try:
        yield schema
    finally:
        with admin.begin() as connection:
            connection.execute(text(f"DROP SCHEMA {schema} CASCADE"))
        admin.dispose()


def _execute(schema: str, statements: list[tuple[str, dict]]) -> None:
    engine = create_engine(_schema_url(schema), future=True)
    with engine.begin() as connection:
        for statement, params in statements:
            connection.execute(text(statement), params)
    engine.dispose()


def _query(schema: str, sql: str, params: dict | None = None) -> list[tuple]:
    engine = create_engine(_schema_url(schema), future=True)
    with engine.connect() as connection:
        rows = connection.execute(text(sql), params or {}).fetchall()
    engine.dispose()
    return [tuple(row) for row in rows]


def _insert_legacy_rows(schema: str, batches: dict[str, int]) -> None:
    """Populate the schema as it existed before import_sequence."""
    tenant_id = str(uuid.uuid4())
    statements = [
        (
            "INSERT INTO tenant (id, name, created_at) VALUES (:id, 'T', :created)",
            {"id": tenant_id, "created": datetime(2026, 1, 1)},
        )
    ]
    for batch_name, row_count in batches.items():
        batch_id = str(uuid.uuid4())
        statements.append(
            (
                "INSERT INTO import_batch (id, name, tenant_id, created_at)"
                " VALUES (:id, :name, :tenant, :created)",
                {
                    "id": batch_id,
                    "name": batch_name,
                    "tenant": tenant_id,
                    "created": datetime(2026, 1, 1),
                },
            )
        )
        for index in range(row_count):
            statements.append(
                (
                    """INSERT INTO financial_record
                       (id, batch_id, reference, source_type, source_document_name,
                        status, validation_errors, raw_payload, created_at, updated_at)
                       VALUES (:id, :batch, :reference, 'CSV', 'legacy.csv', 'VALID',
                               '[]', '{}', :created, :updated)""",
                    {
                        "id": str(uuid.uuid4()),
                        "batch": batch_id,
                        "reference": f"{batch_name}-REF",
                        "created": datetime(2026, 1, 1) + timedelta(minutes=index),
                        "updated": datetime(2026, 1, 1),
                    },
                )
            )
    _execute(schema, statements)


def _insert_batch_only(schema: str) -> None:
    """A tenant with a batch and no user: what a pre-authentication database holds."""
    tenant_id = str(uuid.uuid4())
    _execute(
        schema,
        [
            (
                "INSERT INTO tenant (id, name, created_at) VALUES (:id, 'Demo Tenant A', :created)",
                {"id": tenant_id, "created": datetime(2026, 1, 1)},
            ),
            (
                "INSERT INTO import_batch (id, name, tenant_id, created_at)"
                " VALUES (:id, 'Before accounts', :tenant, :created)",
                {
                    "id": str(uuid.uuid4()),
                    "tenant": tenant_id,
                    "created": datetime(2026, 1, 1),
                },
            ),
        ],
    )


@pytest.fixture
def legacy_database(migration_schema, monkeypatch) -> str:
    """A populated schema from before import_sequence existed.

    These tests upgrade a database that holds data, which the authentication
    revision refuses to do by default. They acknowledge that deliberately: the
    subject here is the backfill, not the account migration.
    """
    monkeypatch.setenv("ALLOW_ORPHANED_DATA", "1")
    command.upgrade(_config(_schema_url(migration_schema)), BEFORE_IMPORT_SEQUENCE)
    _insert_legacy_rows(migration_schema, {"batch-a": 3, "batch-b": 2})
    return migration_schema


def _sequences_by_batch(schema: str) -> dict[str, list[int]]:
    rows = _query(
        schema,
        """SELECT b.name, r.import_sequence
           FROM financial_record r JOIN import_batch b ON b.id = r.batch_id
           ORDER BY b.name, r.import_sequence""",
    )
    grouped: dict[str, list[int]] = {}
    for name, sequence in rows:
        grouped.setdefault(name, []).append(sequence)
    return grouped


def _columns(schema: str, table: str) -> dict[str, tuple]:
    """data_type, character_maximum_length, is_nullable, column_default."""
    rows = _query(
        schema,
        """SELECT column_name, data_type, character_maximum_length,
                  is_nullable, column_default
           FROM information_schema.columns
           WHERE table_schema = :schema AND table_name = :table""",
        {"schema": schema, "table": table},
    )
    return {row[0]: row[1:] for row in rows}


def test_upgrade_succeeds_on_a_populated_database(legacy_database):
    command.upgrade(_config(_schema_url(legacy_database)), "head")


def test_existing_rows_receive_distinct_positions_per_batch(legacy_database):
    """The defect this test exists for: every row landing on sequence 0.

    With a shared position no record has a predecessor, so `references_before`
    returns nothing and every duplicate in an existing database would quietly
    become valid on its next revalidation.
    """
    command.upgrade(_config(_schema_url(legacy_database)), "head")

    sequences = _sequences_by_batch(legacy_database)
    assert sequences["batch-a"] == [0, 1, 2]
    assert sequences["batch-b"] == [0, 1]


def test_positions_restart_at_zero_for_each_batch(legacy_database):
    command.upgrade(_config(_schema_url(legacy_database)), "head")

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
    """Assert the declared type, and on PostgreSQL that assertion has teeth.

    A bounded column here would make an over-long value fail the INSERT rather
    than be reported -- and because an import runs in one transaction, one bad
    cell would lose the whole file.
    """
    command.upgrade(_config(_schema_url(legacy_database)), "head")

    data_type, max_length, _, _ = _columns(legacy_database, table)[column]

    assert data_type == "text", (
        f"{table}.{column} is {data_type}({max_length}); a bounded type would make "
        "PostgreSQL reject an invalid value and fail the whole import"
    )


def test_column_has_no_server_default(legacy_database):
    """A default would quietly assign 0 to a code path that forgot to allocate."""
    command.upgrade(_config(_schema_url(legacy_database)), "head")

    _, _, is_nullable, default = _columns(legacy_database, "financial_record")["import_sequence"]

    assert default is None, "import_sequence must not carry a server default"
    assert is_nullable == "NO", "import_sequence must be NOT NULL"


class TestAuthenticationMigrationRefusesToOrphanData:
    """Adding accounts to an app that had none is breaking, so it stops.

    Batches used to belong to a workspace with no user. After this revision a
    workspace is only reachable through an account, so that data would become
    invisible. Completing while quietly disconnecting it is worse than
    refusing, so the migration refuses and says why.
    """

    BEFORE_AUTH = "1653257e517f"
    ESCAPE_HATCH = "ALLOW_ORPHANED_DATA"

    @pytest.fixture
    def populated_before_auth(self, migration_schema, monkeypatch) -> str:
        monkeypatch.delenv(self.ESCAPE_HATCH, raising=False)
        command.upgrade(_config(_schema_url(migration_schema)), self.BEFORE_AUTH)
        _insert_batch_only(migration_schema)
        return migration_schema

    def test_an_empty_database_upgrades_normally(self, migration_schema):
        command.upgrade(_config(_schema_url(migration_schema)), "head")

    def test_a_populated_database_is_refused(self, populated_before_auth):
        with pytest.raises(RuntimeError, match="created before accounts existed"):
            command.upgrade(_config(_schema_url(populated_before_auth)), "head")

    def test_the_refusal_says_how_to_proceed(self, populated_before_auth):
        with pytest.raises(RuntimeError) as raised:
            command.upgrade(_config(_schema_url(populated_before_auth)), "head")

        assert self.ESCAPE_HATCH in str(raised.value)
        assert "empty database" in str(raised.value)

    def _tables(self, schema: str) -> set[str]:
        return {
            row[0]
            for row in _query(
                schema,
                "SELECT table_name FROM information_schema.tables WHERE table_schema = :schema",
                {"schema": schema},
            )
        }

    def test_nothing_is_migrated_when_refused(self, populated_before_auth):
        with pytest.raises(RuntimeError):
            command.upgrade(_config(_schema_url(populated_before_auth)), "head")

        assert "user" not in self._tables(populated_before_auth), (
            "the schema must be left as it was"
        )

    def test_the_escape_hatch_allows_an_informed_upgrade(self, populated_before_auth, monkeypatch):
        """Accepting the consequence is a deliberate act, not a default."""
        monkeypatch.setenv(self.ESCAPE_HATCH, "1")
        command.upgrade(_config(_schema_url(populated_before_auth)), "head")

        assert "user" in self._tables(populated_before_auth)
