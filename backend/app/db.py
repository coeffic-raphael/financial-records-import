"""Engine, session and the SQLite pragmas the application depends on."""

from collections.abc import Iterator
from decimal import Decimal

from sqlalchemy import Engine, Numeric, String, create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.types import TypeDecorator

from app.config import get_settings


class Money(TypeDecorator):
    """Exact decimal storage on every engine.

    SQLite has no decimal type: a plain `Numeric` column is stored with REAL
    affinity, so the value passes through a float on its way to disk. At our
    magnitudes the round-trip happens to be lossless, but it contradicts the
    project rule that money never touches a float -- and it would stop being
    lossless for values needing more than ~15 significant digits.

    So the value is stored as TEXT on SQLite and as NUMERIC on PostgreSQL.
    Note that the PostgreSQL side is not exercised yet: it will be once a
    PostgreSQL service joins CI.

    Consequence, deliberately accepted: amounts cannot be summed in SQL on
    SQLite. Batch summaries aggregate in Python instead, which is fine for the
    tens of records a batch holds. Should SQL-side aggregation ever be needed,
    integer cents would be the alternative.
    """

    impl = Numeric(18, 2)
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "sqlite":
            return dialect.type_descriptor(String(32))
        return dialect.type_descriptor(Numeric(18, 2))

    def process_bind_param(self, value: Decimal | None, dialect) -> object:
        if value is None:
            return None
        return f"{value:.2f}" if dialect.name == "sqlite" else value

    def process_result_value(self, value: object, dialect) -> Decimal | None:
        if value is None:
            return None
        return Decimal(value) if dialect.name == "sqlite" else value


class Base(DeclarativeBase):
    pass


@event.listens_for(Engine, "connect")
def _set_sqlite_pragmas(dbapi_connection, connection_record) -> None:
    """Pragmas SQLite does not apply by default.

    - foreign_keys=ON: without it SQLite IGNORES foreign keys entirely, so the
      declared ON DELETE CASCADE would silently do nothing -- and the gap would
      only surface on PostgreSQL, where it does apply.
    - journal_mode=WAL + busy_timeout: readers no longer block on a writer, and
      concurrent writers wait instead of failing with "database is locked".
      Needed once PDF extraction runs in background tasks.
    """
    if type(dbapi_connection).__module__.startswith("sqlite3"):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.close()


def create_app_engine(database_url: str | None = None) -> Engine:
    url = database_url or get_settings().database_url
    connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
    return create_engine(url, connect_args=connect_args, future=True)


engine = create_app_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_session() -> Iterator[Session]:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
