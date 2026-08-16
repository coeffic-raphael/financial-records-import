"""Access and refresh credentials.

Two different things, deliberately built differently:

- the ACCESS token is a signed JWT, short-lived, and carries the tenant. It is
  never stored anywhere, on either side.
- the REFRESH token is an opaque random value. Only its hash is stored, and it
  is rotated on every use.

That split is what answers "how do you revoke a JWT?": you do not. You revoke
the refresh token, and the access token expires on its own within minutes.
"""

import hashlib
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import jwt

TOKEN_TYPE_ACCESS = "access"
REFRESH_TOKEN_BYTES = 32


class InvalidTokenError(Exception):
    """Signature, expiry or shape is wrong. The reason is never told to the client."""


@dataclass(frozen=True, slots=True)
class AccessTokenClaims:
    user_id: str
    tenant_id: str


def issue_access_token(
    user_id: str, tenant_id: str, secret: str, algorithm: str, ttl_minutes: int
) -> str:
    """Sign a short-lived token carrying the tenant.

    The tenant travels IN the token, which is what makes authentication and
    tenant scoping a single mechanism: no request may ever say which tenant it
    belongs to.
    """
    now = datetime.now(UTC)
    payload = {
        "sub": user_id,
        "tenant_id": tenant_id,
        "type": TOKEN_TYPE_ACCESS,
        # A unique id per token. Without it, two tokens issued for the same user
        # within the same second are byte-identical, since iat and exp only have
        # second resolution -- which makes a single session indistinguishable
        # from another in a log, and a rotation impossible to observe.
        "jti": secrets.token_urlsafe(8),
        "iat": now,
        "exp": now + timedelta(minutes=ttl_minutes),
    }
    return jwt.encode(payload, secret, algorithm=algorithm)


def read_access_token(token: str, secret: str, algorithm: str) -> AccessTokenClaims:
    """Verify and unpack. Any problem is one and the same error to the caller."""
    try:
        payload = jwt.decode(token, secret, algorithms=[algorithm])
    except jwt.PyJWTError as error:
        raise InvalidTokenError("The access token is not usable.") from error

    if payload.get("type") != TOKEN_TYPE_ACCESS:
        # A refresh token presented as an access token must not be accepted.
        raise InvalidTokenError("Wrong token type.")

    user_id, tenant_id = payload.get("sub"), payload.get("tenant_id")
    if not user_id or not tenant_id:
        raise InvalidTokenError("The token is missing required claims.")

    return AccessTokenClaims(user_id=user_id, tenant_id=tenant_id)


def generate_refresh_token() -> tuple[str, str]:
    """Return (token to send, hash to store).

    The plain value exists only in this return and in the client's cookie. A
    database dump therefore yields no usable session.
    """
    token = secrets.token_urlsafe(REFRESH_TOKEN_BYTES)
    return token, hash_refresh_token(token)


def hash_refresh_token(token: str) -> str:
    """SHA-256, and that is the right choice HERE.

    A password needs a slow hash because it has little entropy. This value has
    256 bits of it, so there is nothing to brute-force, and a fast digest is
    what allows an indexed lookup rather than scanning every stored token.
    """
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
