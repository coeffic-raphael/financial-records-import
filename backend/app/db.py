"""Engine, session factory and the declarative base."""

from collections.abc import Iterator

from sqlalchemy import Engine, Numeric, create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings

# Migration 05981b87a213 names this type in five column definitions. A migration
# that has been committed is history: it must keep running unchanged, so the
# symbol stays importable. `sa.Numeric` takes the same keyword arguments the
# migration passes (precision, scale) and returns Decimal values, so the
# substitution is transparent.
#
# Nothing else uses it. Models declare Numeric(18, 2) directly.
Money = Numeric


class Base(DeclarativeBase):
    pass


def create_app_engine(database_url: str | None = None) -> Engine:
    return create_engine(database_url or get_settings().database_url, future=True)


engine = create_app_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_session_factory() -> sessionmaker:
    """The factory background tasks use to open their own session.

    A background task cannot reuse the request session -- it is closed once the
    response is sent -- so it must build one. Reaching for the module-level
    SessionLocal directly would hard-wire it to whatever engine the process
    started with, which is invisible until something needs a different one: a
    test would then silently write to the development database.
    """
    return SessionLocal


def get_session() -> Iterator[Session]:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
