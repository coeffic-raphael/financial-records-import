"""SQLAlchemy models.

Two schema-level decisions deserve attention, because both are cases where the
"obviously correct" constraint would break an explicit requirement.
"""

from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON

from app.db import Base, ExactDecimal
from app.domain.enums import JobStatus, RecordStatus, SourceType


def _uuid() -> str:
    return str(uuid4())


def _now() -> datetime:
    return datetime.now(UTC)


# UUIDs are stored as CHAR(36) rather than a native type: PostgreSQL has UUID,
# SQLite does not, and a portable column keeps the migration honest.
UUID_LEN = 36


class Tenant(Base):
    __tablename__ = "tenant"

    id: Mapped[str] = mapped_column(String(UUID_LEN), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now, nullable=False)

    batches: Mapped[list["ImportBatch"]] = relationship(
        back_populates="tenant", cascade="all, delete-orphan"
    )


class User(Base):
    """A person, belonging to exactly one tenant.

    Sharing a tenant between colleagues would need an invitation flow; here each
    registration creates its own tenant, which is documented as a limitation.
    """

    __tablename__ = "user"

    id: Mapped[str] = mapped_column(String(UUID_LEN), primary_key=True, default=_uuid)
    email: Mapped[str] = mapped_column(String(320), nullable=False, unique=True)

    # TEXT like every other user-supplied value: a display name has no natural
    # length, and a narrow column would refuse a long one instead of reporting it.
    name: Mapped[str] = mapped_column(Text, nullable=False)

    # Never the password itself, and never returned by any schema: no response
    # DTO exposes this column.
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)

    tenant_id: Mapped[str] = mapped_column(
        String(UUID_LEN), ForeignKey("tenant.id", ondelete="CASCADE"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now, nullable=False)

    tenant: Mapped[Tenant] = relationship()

    __table_args__ = (Index("ix_user_tenant", "tenant_id"),)


class RefreshToken(Base):
    """A rotating, revocable session credential.

    The token itself is never stored -- only a hash of it, so a database leak
    does not hand over live sessions.

    SHA-256 rather than Argon2 here, deliberately: this is a 256-bit random
    value, not a low-entropy password, so there is nothing to brute-force and an
    indexed lookup by hash is what makes verification a single query instead of
    a scan.
    """

    __tablename__ = "refresh_token"

    id: Mapped[str] = mapped_column(String(UUID_LEN), primary_key=True, default=_uuid)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    user_id: Mapped[str] = mapped_column(
        String(UUID_LEN), ForeignKey("user.id", ondelete="CASCADE"), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now, nullable=False)

    user: Mapped[User] = relationship()

    __table_args__ = (Index("ix_refresh_token_user", "user_id"),)


class ImportBatch(Base):
    __tablename__ = "import_batch"

    id: Mapped[str] = mapped_column(String(UUID_LEN), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now, nullable=False)

    # The single edge carrying tenant isolation. financial_record inherits it
    # through batch_id and deliberately does NOT duplicate tenant_id: two
    # sources of truth for one fact eventually diverge.
    tenant_id: Mapped[str] = mapped_column(
        String(UUID_LEN), ForeignKey("tenant.id", ondelete="CASCADE"), nullable=False
    )

    tenant: Mapped[Tenant] = relationship(back_populates="batches")
    records: Mapped[list["FinancialRecord"]] = relationship(
        back_populates="batch", cascade="all, delete-orphan"
    )

    __table_args__ = (Index("ix_import_batch_tenant", "tenant_id"),)


class FinancialRecord(Base):
    """The common model from the data dictionary, plus technical columns.

    NO UNIQUE(batch_id, reference) CONSTRAINT -- deliberately.
    The assignment requires importing every row rather than rejecting the file,
    and the supplied CSV contains an intentional duplicate (TX-2026-0003).
    A uniqueness constraint would crash that insert instead of persisting the
    row as NEEDS_REVIEW. Uniqueness is an application-level validation rule.
    Please do not "fix" this by adding the constraint.

    CHECK CONSTRAINTS ONLY ON SYSTEM-CONTROLLED ENUMS.
    `status` and `source_type` are set by the application, so they are
    constrained. `currency`, `category` and `payment_method` carry USER data and
    must be able to hold unsupported values -- that is the whole point of
    persisting an invalid row as NEEDS_REVIEW. A CHECK on `currency` would
    reject the JPY row and break the import, exactly like the UNIQUE above.
    """

    __tablename__ = "financial_record"

    id: Mapped[str] = mapped_column(String(UUID_LEN), primary_key=True, default=_uuid)
    batch_id: Mapped[str] = mapped_column(
        String(UUID_LEN), ForeignKey("import_batch.id", ondelete="CASCADE"), nullable=False
    )

    # Arrival order within the batch, assigned by the server; it continues
    # across uploads. Allocation is not concurrency-safe -- see
    # services.records.next_import_sequence. It exists to make the duplicate
    # policy STABLE: "the first
    # occurrence wins" needs an explicit order, and a UUID carries none. Without
    # it, revalidating the first of two duplicates would see the second and flag
    # the first as a duplicate of itself -- flipping a VALID record to
    # NEEDS_REVIEW with no correction having taken place.
    import_sequence: Mapped[int] = mapped_column(Integer, nullable=False)

    # --- Data dictionary fields ---
    # Every user-supplied column below is TEXT, not a bounded VARCHAR.
    #
    # A narrow column is the third form of the mistake this project keeps making:
    # being strict about data the user controls. country VARCHAR(2) reads like
    # careful design, but PostgreSQL would refuse to store the invalid value
    # "LUX" -- and since the import runs in one transaction, one bad cell would
    # lose the whole file, contradicting the requirement to import every row.
    # SQLite ignores VARCHAR limits, so no test could have caught it.
    #
    # Plausibility limits live in the domain (MAX_FIELD_LENGTHS) where breaking
    # one is a reportable business error rather than a failed INSERT.
    reference: Mapped[str | None] = mapped_column(Text)
    # Real Date columns: normalization already turned unreadable input into
    # None, and the original string is preserved in raw_payload.
    transaction_date: Mapped[date | None] = mapped_column(Date)
    value_date: Mapped[date | None] = mapped_column(Date)
    description: Mapped[str | None] = mapped_column(Text)
    gross_amount: Mapped[Decimal | None] = mapped_column(ExactDecimal(18, 2))
    fee_amount: Mapped[Decimal | None] = mapped_column(ExactDecimal(18, 2))
    tax_amount: Mapped[Decimal | None] = mapped_column(ExactDecimal(18, 2))
    net_amount: Mapped[Decimal | None] = mapped_column(ExactDecimal(18, 2))
    currency: Mapped[str | None] = mapped_column(Text)
    counterparty_name: Mapped[str | None] = mapped_column(Text)
    counterparty_account: Mapped[str | None] = mapped_column(Text)
    country: Mapped[str | None] = mapped_column(Text)
    category: Mapped[str | None] = mapped_column(Text)
    invoice_number: Mapped[str | None] = mapped_column(Text)
    payment_method: Mapped[str | None] = mapped_column(Text)

    source_type: Mapped[str] = mapped_column(String(8), nullable=False)
    source_document_name: Mapped[str] = mapped_column(Text, nullable=False)
    # Storage stays as generous as for amounts, deliberately. A tight
    # NUMERIC(3, 2) would not have enforced [0, 1] anyway -- it accepts 9.99 --
    # while making 10.00 a failed INSERT instead of a reportable error. The
    # range is a business rule; see validation.check_confidence_range.
    extraction_confidence: Mapped[Decimal | None] = mapped_column(ExactDecimal(18, 2))
    field_confidence: Mapped[dict | None] = mapped_column(JSON)

    status: Mapped[str] = mapped_column(String(16), nullable=False)
    validation_errors: Mapped[list] = mapped_column(JSON, nullable=False, default=list)

    # Source of truth for revalidation: a correction merges into raw_payload and
    # replays the exact same pipeline as the initial import.
    raw_payload: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=_now, onupdate=_now, nullable=False
    )

    batch: Mapped[ImportBatch] = relationship(back_populates="records")

    __table_args__ = (
        CheckConstraint(
            "status IN ({})".format(", ".join(f"'{s.value}'" for s in RecordStatus)),
            name="ck_financial_record_status",
        ),
        CheckConstraint(
            "source_type IN ({})".format(", ".join(f"'{s.value}'" for s in SourceType)),
            name="ck_financial_record_source_type",
        ),
        Index("ix_financial_record_batch_status", "batch_id", "status"),
        Index("ix_financial_record_batch_sequence", "batch_id", "import_sequence"),
    )


class ExtractionJob(Base):
    """Tracks one PDF extraction. Populated by the AI connector.

    PROCESSING lives here, never on FinancialRecord.status: the data dictionary
    fixes that enum to three values and adding a technical state would break
    conformance with the common model.
    """

    __tablename__ = "extraction_job"

    id: Mapped[str] = mapped_column(String(UUID_LEN), primary_key=True, default=_uuid)
    batch_id: Mapped[str] = mapped_column(
        String(UUID_LEN), ForeignKey("import_batch.id", ondelete="CASCADE"), nullable=False
    )
    # TEXT for the same reason as source_document_name: it carries a
    # client-supplied filename, and a long one must not break job creation
    # before extraction has even started.
    document_name: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    provider: Mapped[str | None] = mapped_column(String(32))
    model: Mapped[str | None] = mapped_column(Text)
    input_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    record_count: Mapped[int | None] = mapped_column(Integer)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=_now, onupdate=_now, nullable=False
    )

    __table_args__ = (
        # Job status is system-controlled, so it is constrained -- same rule as
        # FinancialRecord.status, and the same reason the user-supplied enums
        # are not.
        CheckConstraint(
            "status IN ({})".format(", ".join(f"'{s.value}'" for s in JobStatus)),
            name="ck_extraction_job_status",
        ),
        Index("ix_extraction_job_batch", "batch_id"),
    )
