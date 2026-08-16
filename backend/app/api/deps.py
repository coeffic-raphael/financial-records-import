"""Shared dependencies.

`current_tenant` is the seam described in the project plan: it exists and every
scoped router already depends on it, but its implementation is provisional. The
authentication stage fills it in WITHOUT touching a single endpoint.

Until then the application behaves as honest single-tenant, with the extension
point visible rather than a half-wired feature.
"""

from typing import Annotated

from fastapi import Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_session
from app.models import Tenant

DEFAULT_TENANT_NAME = "Demo Tenant A"

SessionDep = Annotated[Session, Depends(get_session)]


def current_tenant(session: SessionDep) -> Tenant:
    """PROVISIONAL: resolves the default tenant.

    Replaced at the authentication stage by tenant resolution from the JWT.
    The contract does not change: callers receive a Tenant, and the tenant id
    will then come from the token, never from the request.

    Scope of the guarantee: declaring this dependency on a router guarantees the
    tenant is RESOLVED for every route it holds. It does NOT guarantee that each
    SQL query filters on it -- that remains the query author's responsibility,
    and it is the parametrised cross-tenant matrix in the test suite that guards
    against a route being added without scoping.
    """
    tenant = session.scalar(select(Tenant).where(Tenant.name == DEFAULT_TENANT_NAME))
    if tenant is None:
        tenant = Tenant(name=DEFAULT_TENANT_NAME)
        session.add(tenant)
        session.commit()
        session.refresh(tenant)
    return tenant


TenantDep = Annotated[Tenant, Depends(current_tenant)]
