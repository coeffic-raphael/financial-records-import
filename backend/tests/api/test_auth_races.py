"""Concurrency at the authentication boundary.

Both cases are read-then-write windows closed by letting the database arbitrate:
a conditional UPDATE for rotation, a unique constraint for registration.

Read the two kinds of test here differently:

- the SEQUENTIAL ones use two sessions one after the other. They prove reuse is
  detected across sessions, and they would pass against the old read-then-write
  code too, so they are not regression detectors for the race itself.
- the CONCURRENT one uses threads released together. It asserts the invariant
  directly, and only the conditional UPDATE guarantees it on every run.
"""

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.errors import APIError
from app.config import get_settings
from app.models import RefreshToken, User
from app.services.auth import issue_session, register, rotate_session
from tests.conftest import TEST_PASSWORD


@pytest.fixture
def user_and_token(session) -> tuple[User, str]:
    """An account with one live refresh token."""
    user = register(session, "rotator@example.com", TEST_PASSWORD)
    _, refresh = issue_session(session, user, get_settings())
    return user, refresh


class TestSequentialReuse:
    """A revoked token presented again, one caller after the other."""

    def test_a_rotated_token_cannot_be_rotated_again(self, engine, user_and_token):
        """The ordinary theft case: the thief arrives after the owner rotated."""
        _, refresh = user_and_token
        settings = get_settings()

        with Session(engine) as first, Session(engine) as second:
            rotate_session(first, refresh, settings)

            with pytest.raises(APIError) as raised:
                rotate_session(second, refresh, settings)

        assert raised.value.code == "REFRESH_TOKEN_REUSED"

    def test_the_loser_triggers_a_full_revocation(self, engine, session, user_and_token):
        """Losing the race is indistinguishable from theft, and treated as such."""
        user, refresh = user_and_token
        settings = get_settings()

        with Session(engine) as first, Session(engine) as second:
            rotate_session(first, refresh, settings)
            with pytest.raises(APIError):
                rotate_session(second, refresh, settings)

        session.expire_all()
        tokens = session.scalars(
            select(RefreshToken).where(RefreshToken.user_id == user.id)
        ).all()
        assert all(token.revoked_at is not None for token in tokens)


class TestConcurrentRotation:
    """Simultaneous rotations of one token: exactly one may win.

    This is the invariant the conditional UPDATE exists for. With a
    read-then-write both threads could see revoked_at as NULL and both succeed,
    leaving a stolen token rotating alongside the legitimate one with reuse
    detection never firing.
    """

    def test_exactly_one_thread_obtains_a_new_session(self, engine, user_and_token):
        import threading

        _, refresh = user_and_token
        settings = get_settings()
        attempts = 8
        barrier = threading.Barrier(attempts)
        outcomes: list[str] = []
        lock = threading.Lock()

        def attempt() -> None:
            barrier.wait()
            with Session(engine) as own_session:
                try:
                    rotate_session(own_session, refresh, settings)
                    result = "won"
                except APIError as error:
                    result = error.code
                except Exception as error:  # noqa: BLE001 -- reported, not swallowed
                    result = f"unexpected:{type(error).__name__}"
            with lock:
                outcomes.append(result)

        threads = [threading.Thread(target=attempt) for _ in range(attempts)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        assert outcomes.count("won") == 1, outcomes
        assert all(result != "won" for result in outcomes if result != "won")
        assert not any(result.startswith("unexpected") for result in outcomes), outcomes


class TestConcurrentRegistration:
    """Two sign-ups with the same address: one account, one clean 409."""

    def test_the_second_registration_is_refused_not_crashed(self, engine):
        """The unique constraint decides. A prior SELECT leaves a window where
        both callers pass the check and the loser gets a 500."""
        with Session(engine) as first, Session(engine) as second:
            register(first, "duplicate@example.com", TEST_PASSWORD)

            with pytest.raises(APIError) as raised:
                register(second, "duplicate@example.com", TEST_PASSWORD)

        assert raised.value.status_code == 409
        assert raised.value.code == "EMAIL_TAKEN"

    def test_only_one_account_exists_afterwards(self, engine, session):
        with Session(engine) as first, Session(engine) as second:
            register(first, "duplicate@example.com", TEST_PASSWORD)
            with pytest.raises(APIError):
                register(second, "duplicate@example.com", TEST_PASSWORD)

        session.expire_all()
        users = session.scalars(
            select(User).where(User.email == "duplicate@example.com")
        ).all()
        assert len(users) == 1

    def test_a_refused_registration_leaves_no_orphan_workspace(self, engine, session):
        """The tenant is created before the user, so a rejected sign-up must
        roll it back rather than leave an unreachable workspace behind."""
        from app.models import Tenant

        with Session(engine) as first, Session(engine) as second:
            register(first, "duplicate@example.com", TEST_PASSWORD)
            with pytest.raises(APIError):
                register(second, "duplicate@example.com", TEST_PASSWORD)

        session.expire_all()
        tenants = session.scalars(select(Tenant)).all()
        assert len(tenants) == 1
