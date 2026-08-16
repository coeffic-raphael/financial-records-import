"""The default test run must never reach the network.

The README tells a reviewer to run `pytest`. Marking the live tests was not
enough: a mark only enables selection, it does not deselect. With a key
configured, a bare `pytest` was making real API calls -- slow, billable, and
failing outright with no network.
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

        with pytest.raises(ValueError, match="GEMINI_API_KEY is required"), TestClient(
            create_app()
        ):
            pass

        get_settings.cache_clear()

    def test_an_unknown_provider_prevents_startup(self, monkeypatch):
        from fastapi.testclient import TestClient

        from app.config import get_settings
        from app.main import create_app

        monkeypatch.setenv("EXTRACTION_PROVIDER", "not-a-provider")
        get_settings.cache_clear()

        with pytest.raises(ValueError, match="Unknown EXTRACTION_PROVIDER"), TestClient(
            create_app()
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
