"""Registration, login, rotation and logout."""

from datetime import UTC, datetime, timedelta

from fastapi import status
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.errors import APIError
from app.config import Settings
from app.models import RefreshToken, Tenant, User
from app.security.passwords import MIN_PASSWORD_LENGTH, hash_password, verify_password
from app.security.tokens import (
    generate_refresh_token,
    hash_refresh_token,
    issue_access_token,
)

# Verified against a real hash when the account does not exist, so that a
# missing account and a wrong password take the same time to answer. Without it,
# response timing tells an attacker which addresses are registered.
_TIMING_DECOY = hash_password("timing-attack-decoy")


def _invalid_credentials() -> APIError:
    """One message for both cases: never reveal which half was wrong."""
    return APIError(
        status.HTTP_401_UNAUTHORIZED, "INVALID_CREDENTIALS", "Invalid email or password."
    )


def register(session: Session, email: str, password: str, name: str) -> User:
    """Create a user and the tenant that belongs to them."""
    email = email.strip().lower()
    name = name.strip()
    if not name:
        raise APIError(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "NAME_REQUIRED", "A name is required."
        )
    if len(password) < MIN_PASSWORD_LENGTH:
        raise APIError(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "WEAK_PASSWORD",
            f"The password must be at least {MIN_PASSWORD_LENGTH} characters long.",
        )
    tenant = Tenant(name=f"{name}'s workspace")
    session.add(tenant)
    session.flush()

    user = User(
        email=email, name=name, password_hash=hash_password(password), tenant_id=tenant.id
    )
    session.add(user)

    # The unique constraint decides, not a prior SELECT. Checking first and then
    # inserting leaves a window where two registrations both pass the check and
    # the second gets a 500 instead of a 409.
    #
    # Note the contrast with `reference` on financial_record, which deliberately
    # has NO unique constraint: there a duplicate must be IMPORTED and flagged,
    # here it must be REFUSED. Different requirements, different mechanisms.
    try:
        session.commit()
    except IntegrityError as error:
        session.rollback()
        raise APIError(
            status.HTTP_409_CONFLICT, "EMAIL_TAKEN", "This email is already registered."
        ) from error

    session.refresh(user)
    return user


def authenticate(session: Session, email: str, password: str) -> User:
    user = session.scalar(select(User).where(User.email == email.strip().lower()))
    if user is None:
        verify_password(password, _TIMING_DECOY)
        raise _invalid_credentials()
    if not verify_password(password, user.password_hash):
        raise _invalid_credentials()
    return user


def issue_session(session: Session, user: User, settings: Settings) -> tuple[str, str]:
    """Return (access token, refresh token). Only the refresh hash is stored."""
    access = issue_access_token(
        user.id,
        user.tenant_id,
        settings.jwt_secret,
        settings.jwt_algorithm,
        settings.access_token_ttl_minutes,
    )
    plain, digest = generate_refresh_token()
    session.add(
        RefreshToken(
            token_hash=digest,
            user_id=user.id,
            expires_at=_now() + timedelta(days=settings.refresh_token_ttl_days),
        )
    )
    session.commit()
    return access, plain


def rotate_session(session: Session, refresh_token: str, settings: Settings) -> tuple[str, str]:
    """Exchange a refresh token for a new pair, revoking the old one.

    REUSE DETECTION. A token that has already been revoked coming back means it
    was copied: the legitimate holder rotated it, so whoever presents it again
    is not alone. Every token of that user is revoked, which logs out both the
    thief and the owner -- the owner signs in again, the thief cannot.

    Without this, rotation is just a more complicated renewal.
    """
    digest = hash_refresh_token(refresh_token)
    stored = session.scalar(select(RefreshToken).where(RefreshToken.token_hash == digest))
    if stored is None:
        raise _invalid_refresh()

    if stored.expires_at < _now():
        raise _invalid_refresh()

    # Claim the token with a CONDITIONAL update rather than read-then-write.
    # Two refreshes arriving together would both have seen revoked_at as NULL
    # and both succeeded, so a stolen token would rotate happily alongside the
    # legitimate one and reuse detection would never fire. Here the database
    # decides: exactly one UPDATE matches, and the loser is treated as reuse.
    claimed = session.execute(
        update(RefreshToken)
        .where(RefreshToken.id == stored.id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=_now())
    )
    if claimed.rowcount != 1:
        session.commit()
        _revoke_all_for_user(session, stored.user_id)
        raise APIError(
            status.HTTP_401_UNAUTHORIZED,
            "REFRESH_TOKEN_REUSED",
            "This session has been terminated. Please sign in again.",
        )

    user = session.get(User, stored.user_id)
    if user is None:
        session.commit()
        raise _invalid_refresh()
    return issue_session(session, user, settings)


def revoke_session(session: Session, refresh_token: str | None) -> None:
    """Log out. Silent when the token is unknown: nothing to reveal."""
    if not refresh_token:
        return
    stored = session.scalar(
        select(RefreshToken).where(RefreshToken.token_hash == hash_refresh_token(refresh_token))
    )
    if stored is not None and stored.revoked_at is None:
        stored.revoked_at = _now()
        session.commit()


def _revoke_all_for_user(session: Session, user_id: str) -> None:
    """Log every session of this user out, in one statement."""
    session.execute(
        update(RefreshToken)
        .where(RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=_now())
    )
    session.commit()


def _now() -> datetime:
    """Naive UTC, matching how the column stores it."""
    return datetime.now(UTC).replace(tzinfo=None)


def _invalid_refresh() -> APIError:
    return APIError(
        status.HTTP_401_UNAUTHORIZED, "INVALID_REFRESH_TOKEN", "Please sign in again."
    )
