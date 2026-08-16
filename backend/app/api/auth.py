"""Authentication router -- the ONLY public one.

Every other router carries a tenant dependency. Making the public surface a
single, named object means a route is protected unless someone deliberately
moves it here, rather than protected only if someone remembered to say so.
"""

from fastapi import APIRouter, Response, status
from fastapi.responses import JSONResponse

from app.api.deps import CurrentUserDep, RefreshCookieDep, SessionDep
from app.config import get_settings
from app.models import User
from app.schemas import LoginRequest, RegisterRequest, SessionOut, UserOut
from app.services.auth import (
    authenticate,
    issue_session,
    register,
    revoke_session,
    rotate_session,
)

public_router = APIRouter(prefix="/auth", tags=["auth"])


def _attach_refresh_cookie(response: Response, token: str) -> None:
    """Set the refresh cookie with the three attributes that matter.

    httponly and samesite are unconditional: the first keeps XSS from reading
    it, the second is what covers CSRF. `secure` is configuration-driven only
    because a Secure cookie is never sent over http://localhost, which would
    make development fail authentication with nothing to show for it.
    """
    settings = get_settings()
    response.set_cookie(
        key=settings.refresh_cookie_name,
        value=token,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="strict",
        max_age=settings.refresh_token_ttl_days * 24 * 3600,
        path="/api/auth",
    )


def _session_response(access_token: str, refresh_token: str, user: User) -> JSONResponse:
    payload = SessionOut(
        access_token=access_token,
        expires_in=get_settings().access_token_ttl_minutes * 60,
        user=UserOut.model_validate(user),
    )
    response = JSONResponse(content=payload.model_dump(mode="json"))
    _attach_refresh_cookie(response, refresh_token)
    return response


@public_router.post("/register", status_code=status.HTTP_201_CREATED, response_model=SessionOut)
def register_user(payload: RegisterRequest, session: SessionDep) -> JSONResponse:
    """Create an account and its workspace, then sign in immediately."""
    user = register(session, payload.email, payload.password)
    access, refresh = issue_session(session, user, get_settings())
    response = _session_response(access, refresh, user)
    response.status_code = status.HTTP_201_CREATED
    return response


@public_router.post("/login", response_model=SessionOut)
def login(payload: LoginRequest, session: SessionDep) -> JSONResponse:
    user = authenticate(session, payload.email, payload.password)
    access, refresh = issue_session(session, user, get_settings())
    return _session_response(access, refresh, user)


@public_router.post("/refresh", response_model=SessionOut)
def refresh(session: SessionDep, refresh_token: RefreshCookieDep) -> JSONResponse:
    """Exchange the refresh cookie for a new pair, rotating it."""
    from app.services.auth import _invalid_refresh

    if not refresh_token:
        raise _invalid_refresh()
    access, new_refresh = rotate_session(session, refresh_token, get_settings())

    from app.security.tokens import read_access_token

    claims = read_access_token(
        access, get_settings().jwt_secret, get_settings().jwt_algorithm
    )
    user = session.get(User, claims.user_id)
    return _session_response(access, new_refresh, user)


@public_router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(session: SessionDep, refresh_token: RefreshCookieDep) -> Response:
    """Revoke server-side AND clear the cookie.

    Clearing only the cookie would leave a live credential in the database;
    revoking only server-side would leave a stale cookie that the next user of
    this browser would send.
    """
    revoke_session(session, refresh_token)
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    response.delete_cookie(
        key=get_settings().refresh_cookie_name,
        path="/api/auth",
        httponly=True,
        secure=get_settings().cookie_secure,
        samesite="strict",
    )
    return response


@public_router.get("/me", response_model=UserOut)
def me(user: CurrentUserDep) -> User:
    return user
