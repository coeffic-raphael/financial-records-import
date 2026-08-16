"""Registration, login, rotation, logout."""

import pytest

from app.models import RefreshToken, User
from app.security.passwords import hash_password, verify_password
from tests.conftest import TEST_PASSWORD

CREDENTIALS = {
    "email": "alice@example.com",
    "name": "Alice Martin",
    "password": TEST_PASSWORD,
}


LOGIN = {"email": CREDENTIALS["email"], "password": CREDENTIALS["password"]}


def _register(client, **overrides):
    return client.post("/api/auth/register", json={**CREDENTIALS, **overrides})


class TestPasswordStorage:
    def test_two_identical_passwords_hash_differently(self):
        """A per-password salt: identical passwords must not share a hash."""
        assert hash_password("same-password") != hash_password("same-password")

    def test_verification_accepts_and_rejects(self):
        stored = hash_password("correct-horse-battery")
        assert verify_password("correct-horse-battery", stored)
        assert not verify_password("wrong", stored)

    def test_the_password_is_never_stored(self, anonymous_client, session):
        _register(anonymous_client)
        user = session.query(User).filter_by(email=CREDENTIALS["email"]).one()

        assert TEST_PASSWORD not in user.password_hash
        assert user.password_hash.startswith("$argon2")

    def test_no_response_ever_carries_the_hash(self, anonymous_client):
        body = _register(anonymous_client).text
        assert "password" not in body
        assert "argon2" not in body


class TestRegistration:
    def test_creates_an_account_and_signs_in(self, anonymous_client):
        response = _register(anonymous_client)

        assert response.status_code == 201
        assert response.json()["access_token"]
        assert response.json()["user"]["email"] == CREDENTIALS["email"]
        assert response.json()["user"]["name"] == "Alice Martin"

    def test_a_missing_name_is_refused(self, anonymous_client):
        response = anonymous_client.post(
            "/api/auth/register",
            json={"email": "bob@example.com", "password": TEST_PASSWORD},
        )
        assert response.status_code == 422

    def test_a_blank_name_is_refused(self, anonymous_client):
        response = _register(anonymous_client, name="   ")
        assert response.status_code == 422

    def test_the_workspace_is_named_after_the_person(self, anonymous_client, session):
        from app.models import Tenant, User

        _register(anonymous_client)
        user = session.query(User).filter_by(email=CREDENTIALS["email"]).one()
        tenant = session.get(Tenant, user.tenant_id)

        assert "Alice Martin" in tenant.name

    def test_creates_its_own_workspace(self, anonymous_client, session):
        _register(anonymous_client)
        user = session.query(User).filter_by(email=CREDENTIALS["email"]).one()
        assert user.tenant_id

    def test_a_duplicate_email_is_refused(self, anonymous_client):
        _register(anonymous_client)
        assert _register(anonymous_client).status_code == 409

    def test_a_short_password_is_refused(self, anonymous_client):
        response = _register(anonymous_client, password="short")
        assert response.status_code == 422
        assert response.json()["code"] == "WEAK_PASSWORD"

    def test_email_is_normalised(self, anonymous_client, session):
        _register(anonymous_client, email="Alice@Example.COM")
        assert session.query(User).filter_by(email="alice@example.com").one()


class TestLogin:
    def test_valid_credentials_return_a_token(self, anonymous_client):
        _register(anonymous_client)
        response = anonymous_client.post("/api/auth/login", json=LOGIN)

        assert response.status_code == 200
        assert response.json()["access_token"]

    @pytest.mark.parametrize(
        "overrides",
        [{"password": "wrong-password-entirely"}, {"email": "nobody@example.com"}],
    )
    def test_bad_credentials_are_refused_identically(self, anonymous_client, overrides):
        """Same code and same message for both, so nothing reveals which
        addresses are registered."""
        _register(anonymous_client)
        response = anonymous_client.post("/api/auth/login", json={**LOGIN, **overrides})

        assert response.status_code == 401
        assert response.json()["code"] == "INVALID_CREDENTIALS"


class TestRefreshCookie:
    def _cookie_header(self, response) -> str:
        return response.headers["set-cookie"]

    def test_the_refresh_token_is_not_in_the_body(self, anonymous_client):
        """It lives in an httpOnly cookie the JavaScript never sees."""
        body = _register(anonymous_client).json()
        assert "refresh" not in str(body).lower()

    def test_the_cookie_is_httponly_and_samesite(self, anonymous_client):
        header = self._cookie_header(_register(anonymous_client)).lower()
        assert "httponly" in header
        assert "samesite=strict" in header

    def test_secure_follows_configuration(self, anonymous_client):
        """False in local development only: a Secure cookie is never sent over
        http://localhost, which would break sign-in with nothing to show."""
        header = self._cookie_header(_register(anonymous_client)).lower()
        assert "secure" not in header  # COOKIE_SECURE=false in the test environment


class TestRotation:
    def test_refresh_returns_a_new_pair(self, anonymous_client):
        first = _register(anonymous_client).json()["access_token"]
        response = anonymous_client.post("/api/auth/refresh")

        assert response.status_code == 200
        assert response.json()["access_token"] != first

    def test_the_previous_token_is_revoked(self, anonymous_client, session):
        _register(anonymous_client)
        anonymous_client.post("/api/auth/refresh")

        tokens = session.query(RefreshToken).all()
        assert len(tokens) == 2
        assert sum(1 for token in tokens if token.revoked_at is not None) == 1

    def test_reusing_a_revoked_token_kills_every_session(self, anonymous_client, session):
        """Reuse means the token was copied, so both holders are logged out.

        Without this, rotation is only a more complicated renewal: a stolen
        token would keep working alongside the legitimate one.
        """
        _register(anonymous_client)
        stolen = anonymous_client.cookies.get("refresh_token")
        anonymous_client.post("/api/auth/refresh")  # rotates; `stolen` is now revoked

        anonymous_client.cookies.set("refresh_token", stolen)
        response = anonymous_client.post("/api/auth/refresh")

        assert response.status_code == 401
        assert response.json()["code"] == "REFRESH_TOKEN_REUSED"
        session.expire_all()
        assert all(token.revoked_at is not None for token in session.query(RefreshToken).all())

    def test_an_unknown_token_is_refused(self, anonymous_client):
        _register(anonymous_client)
        anonymous_client.cookies.set("refresh_token", "not-a-real-token")

        assert anonymous_client.post("/api/auth/refresh").status_code == 401


class TestLogout:
    def test_revokes_server_side_and_clears_the_cookie(self, anonymous_client, session):
        """Clearing only the cookie would leave a live credential in the
        database; revoking only server-side would leave a stale cookie for the
        next person using this browser."""
        _register(anonymous_client)
        response = anonymous_client.post("/api/auth/logout")

        assert response.status_code == 204
        session.expire_all()
        assert all(token.revoked_at for token in session.query(RefreshToken).all())

    def test_the_revoked_token_can_no_longer_refresh(self, anonymous_client):
        _register(anonymous_client)
        anonymous_client.post("/api/auth/logout")

        assert anonymous_client.post("/api/auth/refresh").status_code == 401


class TestAccessControl:
    def test_me_returns_the_current_user(self, client):
        body = client.get("/api/auth/me").json()
        assert body["email"] == "owner@example.com"
        assert body["name"] == "Test Owner"

    def test_a_protected_route_needs_a_token(self, anonymous_client):
        response = anonymous_client.get("/api/batches")
        assert response.status_code == 401
        assert response.json()["code"] == "NOT_AUTHENTICATED"

    @pytest.mark.parametrize(
        "header",
        ["", "Bearer", "Bearer ", "Basic abc", "bearer not-a-jwt", "Bearer a.b.c"],
    )
    def test_malformed_authorization_is_refused(self, anonymous_client, header):
        anonymous_client.headers["Authorization"] = header
        assert anonymous_client.get("/api/batches").status_code == 401

    def test_a_token_signed_with_another_secret_is_refused(self, anonymous_client):
        from app.security.tokens import issue_access_token

        forged = issue_access_token("u", "t", "attacker-secret-32-chars-minimum!", "HS256", 15)
        anonymous_client.headers["Authorization"] = f"Bearer {forged}"

        assert anonymous_client.get("/api/batches").status_code == 401

    def test_an_expired_token_is_refused(self, anonymous_client):
        from app.config import get_settings
        from app.security.tokens import issue_access_token

        settings = get_settings()
        expired = issue_access_token(
            "u", "t", settings.jwt_secret, settings.jwt_algorithm, ttl_minutes=-1
        )
        anonymous_client.headers["Authorization"] = f"Bearer {expired}"

        assert anonymous_client.get("/api/batches").status_code == 401

    def test_a_refresh_token_is_not_an_access_token(self, anonymous_client):
        """Presenting the opaque refresh value as a bearer must not work."""
        _register(anonymous_client)
        refresh = anonymous_client.cookies.get("refresh_token")
        anonymous_client.headers["Authorization"] = f"Bearer {refresh}"

        assert anonymous_client.get("/api/batches").status_code == 401
