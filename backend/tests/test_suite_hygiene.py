"""The default test run must never reach the network -- nor the working tree.

The README tells a reviewer to run `pytest`. Marking the live tests was not
enough: a mark only enables selection, it does not deselect. With a key
configured, a bare `pytest` was making real API calls -- slow, billable, and
failing outright with no network.

The second half is the same lesson applied to disk: the suite must not write
into the repository either.
"""

import ast
import tomllib
from pathlib import Path

import pytest

from tests.conftest import BACKEND_ROOT


@pytest.fixture(scope="module")
def pytest_config() -> dict:
    content = (BACKEND_ROOT / "pyproject.toml").read_bytes()
    return tomllib.loads(content.decode())["tool"]["pytest"]["ini_options"]


def test_live_tests_are_excluded_by_default(pytest_config):
    assert "not live" in pytest_config["addopts"]


def test_the_live_marker_is_declared(pytest_config):
    assert any(marker.startswith("live:") for marker in pytest_config["markers"])


SDK_MODULES = {"google.genai", "google", "openai"}


def _imported_modules(source: str) -> set[str]:
    """Real import statements only.

    A textual search would match the string literals in this very file, which is
    exactly what happened the first time it was written.
    """
    modules: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
    return modules


class TestTheSuiteWritesOutsideTheRepository:
    """Uploaded documents must land somewhere disposable.

    The database is isolated by overriding `get_session`, so the settings'
    `database_url` is never consulted while a request is handled. The upload
    directory is not: the route calls `get_settings()` directly, and no
    dependency override can reach that. Nothing in the suite noticed, because a
    test only ever reads back the document it just created -- 3 853 orphaned
    files had accumulated in `backend/uploads/` before anyone counted them.

    It matters more once Docker mounts that directory as a named volume: the
    same behaviour stops being a messy folder and becomes a leak that survives
    restarts.
    """

    def test_uploads_do_not_go_into_the_repository(self):
        from app.config import get_settings

        target = Path(get_settings().upload_storage_dir).resolve()
        assert not target.is_relative_to(BACKEND_ROOT), (
            f"tests would write uploaded documents into the repository at {target}"
        )

    def test_an_upload_really_lands_there(self, client, batch, sample_csv):
        """Asserting on the setting alone would pass even if nothing used it."""
        from app.config import get_settings
        from tests.conftest import upload_csv

        target = Path(get_settings().upload_storage_dir).resolve()
        before = {path.name for path in target.iterdir()} if target.exists() else set()

        upload_csv(client, batch["id"], sample_csv, "hygiene.csv")

        assert {path.name for path in target.iterdir()} - before, (
            "the upload wrote nothing where the setting points"
        )


def test_no_test_module_imports_a_provider_sdk():
    """A double is injected at the dependency; no test needs an SDK directly."""
    offenders = []
    for path in Path(BACKEND_ROOT / "tests").rglob("test_*.py"):
        if path.name == "test_live.py":
            continue
        if _imported_modules(path.read_text()) & SDK_MODULES:
            offenders.append(path.name)
    assert offenders == []


class TestStartupRefusesBadConfiguration:
    """A misconfigured provider must stop the application, not the first upload.

    Building it lazily meant someone could watch the app start, believe it
    healthy, and only discover the missing key by handing it a document.
    """

    def test_a_missing_key_prevents_startup(self, monkeypatch):
        from fastapi.testclient import TestClient

        from app.config import get_settings
        from app.main import create_app

        monkeypatch.setenv("EXTRACTION_PROVIDER", "gemini")
        monkeypatch.setenv("GEMINI_API_KEY", "")
        monkeypatch.setenv("OPENAI_API_KEY", "")
        get_settings.cache_clear()

        with (
            pytest.raises(ValueError, match="GEMINI_API_KEY is required"),
            TestClient(create_app()),
        ):
            pass

        get_settings.cache_clear()

    def test_an_unknown_provider_prevents_startup(self, monkeypatch):
        from fastapi.testclient import TestClient

        from app.config import get_settings
        from app.main import create_app

        monkeypatch.setenv("EXTRACTION_PROVIDER", "not-a-provider")
        get_settings.cache_clear()

        with (
            pytest.raises(ValueError, match="Unknown EXTRACTION_PROVIDER"),
            TestClient(create_app()),
        ):
            pass

        get_settings.cache_clear()

    def test_mock_starts_with_no_credentials_at_all(self, monkeypatch):
        from fastapi.testclient import TestClient

        from app.config import get_settings
        from app.main import create_app

        monkeypatch.setenv("EXTRACTION_PROVIDER", "mock")
        monkeypatch.setenv("GEMINI_API_KEY", "")
        get_settings.cache_clear()

        with TestClient(create_app()) as client:
            assert client.get("/api/health").json() == {"status": "ok"}

        get_settings.cache_clear()


class TestSigningSecretIsChecked:
    """A secret too short weakens HS256, and PyJWT only warns at runtime."""

    def test_a_short_secret_prevents_startup(self, monkeypatch):
        from fastapi.testclient import TestClient

        from app.config import get_settings
        from app.main import create_app

        monkeypatch.setenv("JWT_SECRET", "too-short")
        monkeypatch.setenv("DEBUG", "false")
        get_settings.cache_clear()

        with pytest.raises(ValueError, match="at least 32"), TestClient(create_app()):
            pass

        get_settings.cache_clear()

    def test_debug_generates_an_ephemeral_secret(self, monkeypatch):
        """Convenient locally, and never reachable outside debug."""
        from fastapi.testclient import TestClient

        from app.config import get_settings
        from app.main import create_app

        monkeypatch.setenv("JWT_SECRET", "")
        monkeypatch.setenv("DEBUG", "true")
        get_settings.cache_clear()

        with TestClient(create_app()) as client:
            assert client.get("/api/health").status_code == 200

        get_settings.cache_clear()
