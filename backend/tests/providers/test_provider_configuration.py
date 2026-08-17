"""Provider construction: settings that must actually reach the SDK."""

import json
import re

from app.providers.gemini import GeminiProvider
from app.providers.schema import ExtractedField, json_schema
from tests.conftest import BACKEND_ROOT


class TestTimeoutIsApplied:
    def test_the_configured_timeout_reaches_the_client(self):
        """It used to be stored on the provider and never passed anywhere.

        A hung call would then hold a semaphore slot until the SDK's own default
        expired, which is not the value anyone configured.
        """
        provider = GeminiProvider("fake-key", "gemini-3.6-flash", timeout_seconds=12.0)
        client = provider._get_client()

        # The SDK counts in milliseconds.
        assert client._api_client._http_options.timeout == 12000


class TestConfidenceIsBounded:
    def test_the_schema_declares_the_range(self):
        """Declared bounds constrain the provider at its end, not just ours."""
        schema = json.dumps(json_schema())
        assert '"maximum": 1.0' in schema or '"maximum":1.0' in schema
        assert '"minimum": 0.0' in schema or '"minimum":0.0' in schema

    def test_an_out_of_range_value_is_clamped_not_rejected(self):
        """Rejecting would discard a usable extraction over metadata."""
        assert ExtractedField(value="x", confidence=5.0).confidence == 1.0
        assert ExtractedField(value="x", confidence=-2.0).confidence == 0.0

    def test_values_in_range_are_untouched(self):
        assert ExtractedField(value="x", confidence=0.42).confidence == 0.42

    def test_a_non_numeric_confidence_still_fails(self):
        """Clamping is for out-of-range numbers, not for nonsense."""
        import pytest
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            ExtractedField(value="x", confidence="very sure")


class TestModelsArePinned:
    """A floating alias would change extraction behaviour with no commit.

    `gpt-5.6` resolves to `gpt-5.6-sol` today and may point elsewhere tomorrow.
    The README states a measurement made against a specific build; if the
    default drifts, that measurement stops describing what runs.
    """

    def test_the_openai_default_names_an_exact_build(self):
        from app.config import Settings

        model = Settings(jwt_secret="x" * 32, database_url="postgresql+psycopg://u@h/d").openai_model
        assert re.search(r"-\d{4}-\d{2}-\d{2}$", model), (
            f"OPENAI_MODEL default {model!r} is an alias, not a pinned build."
        )

    def test_the_documented_default_matches_the_code(self):
        """§5 and .env.example both quote this value; drift makes one of them lie."""
        from app.config import Settings

        code_default = Settings(
            jwt_secret="x" * 32, database_url="postgresql+psycopg://u@h/d"
        ).openai_model
        documented = {
            line.split("=", 1)[1].strip()
            for line in (BACKEND_ROOT / ".env.example").read_text().splitlines()
            if line.startswith("OPENAI_MODEL=")
        }
        assert documented == {code_default}, (
            f".env.example documents {documented} but the code default is {code_default!r}."
        )
