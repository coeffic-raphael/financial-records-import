"""Real provider calls.

Marked `live` and skipped unless a key is configured, so the ordinary suite
stays hermetic and offline. Run them explicitly with:

    pytest -m live

Their purpose is narrow but important: prove the connector actually works
against the real API, which no double can establish.
"""

import pytest

from app.config import get_settings
from app.providers.gemini import GeminiProvider
from app.providers.schema import record_confidence
from tests.conftest import SAMPLES

pytestmark = pytest.mark.live

settings = get_settings()
requires_gemini = pytest.mark.skipif(
    not settings.gemini_api_key, reason="GEMINI_API_KEY is not configured"
)


@pytest.fixture(scope="module")
def gemini() -> GeminiProvider:
    return GeminiProvider(
        settings.gemini_api_key, settings.gemini_model, settings.extraction_timeout_seconds
    )


@requires_gemini
def test_invoice_extraction(gemini):
    """The supplied legal invoice totals 4,680.00 EUR."""
    content = (SAMPLES / "invoice_legal_services.pdf").read_bytes()

    result = gemini.extract(content, "invoice_legal_services.pdf")

    assert len(result.records) == 1, "an invoice must yield exactly one record"
    record = result.records[0]
    assert record["currency"] == "EUR"
    assert "INV-LX-441" in (record["invoice_number"] or record["reference"] or "")
    assert "4680" in (record["net_amount"] or "").replace(",", "").replace(" ", "")


@requires_gemini
def test_usage_is_reported(gemini):
    """Token accounting must come back, or cost tracking is fiction."""
    content = (SAMPLES / "invoice_software_subscription.pdf").read_bytes()

    result = gemini.extract(content, "invoice_software_subscription.pdf")

    assert result.usage is not None
    assert result.usage.provider == "gemini"
    assert result.usage.input_tokens and result.usage.input_tokens > 0
    assert result.usage.duration_ms >= 0


@requires_gemini
def test_bank_statement_yields_several_records(gemini):
    """The supplied statement holds eight transaction lines."""
    content = (SAMPLES / "bank_statement_july_2026.pdf").read_bytes()

    result = gemini.extract(content, "bank_statement_july_2026.pdf")

    assert len(result.records) >= 2, "a statement must not collapse into one record"
    balances = {"323500", "323250", "318570", "319815.35"}
    amounts = {
        (r["net_amount"] or "").replace(",", "").replace(" ", "") for r in result.records
    }
    assert not amounts & balances, "running balances were taken instead of line amounts"


@requires_gemini
def test_confidence_is_reported_per_field(gemini):
    content = (SAMPLES / "invoice_legal_services.pdf").read_bytes()

    result = gemini.extract(content, "invoice_legal_services.pdf")

    scores = result.field_confidence[0]
    assert all(0.0 <= value <= 1.0 for value in scores.values())
    assert 0.0 <= record_confidence(scores) <= 1.0
