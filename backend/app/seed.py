"""Demonstration accounts.

Authentication creates an obstacle the assignment did not have: a reviewer
clones the project, starts it, and meets a sign-in screen. Three things prevent
that from turning a bonus into a liability -- this script, the credentials
printed at the top of the README, and registration staying open.

Two accounts rather than one, deliberately: they make tenant isolation
observable by hand, not only in the test suite.

Run with:  python -m app.seed
"""

import logging

from sqlalchemy import select

from app.db import SessionLocal
from app.models import ImportBatch, Tenant, User
from app.services.auth import register

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

DEMO_ACCOUNTS = [
    ("demo@example.com", "demo-password-123"),
    ("second@example.com", "demo-password-123"),
]


def seed() -> None:
    with SessionLocal() as session:
        for email, password in DEMO_ACCOUNTS:
            if session.scalar(select(User).where(User.email == email)) is not None:
                logger.info("%-22s already exists", email)
                continue
            register(session, email, password)
            logger.info("%-22s created with its own workspace", email)

    _report_orphaned_tenants()

    logger.info("")
    logger.info("Sign in with either account. Each sees only its own batches,")
    logger.info("which is the quickest way to see tenant isolation at work.")


def _report_orphaned_tenants() -> None:
    """Name the data that the authentication migration made unreachable.

    A tenant with no user cannot be signed into, so whatever it holds is
    invisible. That happens to databases populated before accounts existed. It
    is reported rather than repaired: attaching a user would mean inventing a
    password, and silence would leave someone wondering where their batches went.
    """
    with SessionLocal() as session:
        orphans = [
            tenant
            for tenant in session.scalars(select(Tenant))
            if session.scalar(select(User).where(User.tenant_id == tenant.id)) is None
        ]
        if not orphans:
            return

        logger.info("")
        logger.warning("%d workspace(s) have no account and are unreachable:", len(orphans))
        for tenant in orphans:
            batches = session.scalars(
                select(ImportBatch).where(ImportBatch.tenant_id == tenant.id)
            ).all()
            logger.warning("  %-30s %d batch(es)", tenant.name, len(batches))
        logger.warning(
            "They predate authentication. Re-import into a signed-in account, or "
            "attach one by hand -- see 'Upgrading an existing database' in the README."
        )


if __name__ == "__main__":
    seed()
