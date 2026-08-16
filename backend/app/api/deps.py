"""Shared dependencies.

`current_tenant` is the seam described in the project plan. It was declared on
every scoped router from the persistence stage onwards, with a provisional
implementation returning a default tenant. Filling it in required changing NO
endpoint -- which is what a well-placed seam is supposed to buy.
"""

from functools import lru_cache
from typing import Annotated

from fastapi import Depends, Request, status
from sqlalchemy.orm import Session, sessionmaker

from app.api.errors import APIError
from app.config import get_settings
from app.db import get_session, get_session_factory
from app.models import Tenant, User
from app.providers.base import ExtractionProvider
from app.providers.registry import build_provider
from app.security.tokens import InvalidTokenError, read_access_token

SessionDep = Annotated[Session, Depends(get_session)]
SessionFactoryDep = Annotated[sessionmaker, Depends(get_session_factory)]


@lru_cache
def _cached_provider() -> ExtractionProvider:
    """Built once: each provider holds a lazily created SDK client."""
    return build_provider(get_settings())


def get_extraction_provider() -> ExtractionProvider:
    """Dependency so tests can substitute a double without touching the network."""
    return _cached_provider()


def _unauthenticated() -> APIError:
    """One answer for every failure: absent, malformed, expired or forged.

    Telling them apart would help an attacker more than a user.
    """
    return APIError(
        status.HTTP_401_UNAUTHORIZED, "NOT_AUTHENTICATED", "Authentication is required."
    )


def get_current_user(request: Request, session: SessionDep) -> User:
    """Resolve the caller from the bearer token, and from nothing else."""
    header = request.headers.get("Authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise _unauthenticated()

    settings = get_settings()
    try:
        claims = read_access_token(token, settings.jwt_secret, settings.jwt_algorithm)
    except InvalidTokenError as error:
        raise _unauthenticated() from error

    user = session.get(User, claims.user_id)
    if user is None or user.tenant_id != claims.tenant_id:
        # A token whose tenant no longer matches the account is not usable, even
        # though its signature is valid.
        raise _unauthenticated()
    return user


CurrentUserDep = Annotated[User, Depends(get_current_user)]


def current_tenant(user: CurrentUserDep, session: SessionDep) -> Tenant:
    """The tenant comes from the TOKEN, never from the request.

    This is the single property the whole isolation story rests on: no path,
    body or header can name a tenant. Everything else -- 404 rather than 403,
    the discovered route matrix -- protects that property rather than replacing
    it.
    """
    tenant = session.get(Tenant, user.tenant_id)
    if tenant is None:
        raise _unauthenticated()
    return tenant


TenantDep = Annotated[Tenant, Depends(current_tenant)]


def get_refresh_cookie(request: Request) -> str | None:
    """Read the cookie under its CONFIGURED name.

    Declaring a parameter named `refresh_token` would bind the name in the
    signature, so renaming the cookie in configuration would change how it is
    written and not how it is read -- an inconsistency that only shows up once
    someone actually renames it.
    """
    return request.cookies.get(get_settings().refresh_cookie_name)


RefreshCookieDep = Annotated[str | None, Depends(get_refresh_cookie)]
