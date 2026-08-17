"""Real provider calls.

Marked `live` and skipped unless a key is configured, so the ordinary suite
stays hermetic and offline. Run them explicitly with:

    pytest -m live

Their purpose is narrow but important: prove the connectors actually work
against the real APIs, which no double can establish.

Both are parametrised. There are two real connectors and a fallback chain that
can put either in front, so testing only one leaves the other unproven exactly
when it is needed -- as the second link, after the first has failed.
"""

import pytest

from app.config import get_settings
from app.providers.base import TransientProviderError
from app.providers.gemini import GeminiProvider
from app.providers.openai import OpenAIProvider
from app.providers.schema import record_confidence
from tests.conftest import SAMPLES

pytestmark = pytest.mark.live

settings = get_settings()


def _providers():
    """One entry per configured connector; a missing key skips its cases."""
    return [
        pytest.param(
            "openai",
            marks=pytest.mark.skipif(
                not settings.openai_api_key, reason="OPENAI_API_KEY is not configured"
            ),
        ),
        pytest.param(
            "gemini",
            marks=pytest.mark.skipif(
                not settings.gemini_api_key, reason="GEMINI_API_KEY is not configured"
            ),
        ),
    ]


@pytest.fixture
def provider(request):
    """The connector under test, wrapped so a rate limit skips rather than fails.

    A 429 means the request reached the API and was authenticated -- it says
    nothing about the connector, and a free tier runs out. Failing on it would
    make the suite report someone else's quota as our defect. A PERMANENT error
    still fails: a bad key or an unknown model is ours to fix.
    """
    name = request.param
    if name == "openai":
        return OpenAIProvider(
            settings.openai_api_key, settings.openai_model, settings.extraction_timeout_seconds
        )
    return GeminiProvider(
        settings.gemini_api_key, settings.gemini_model, settings.extraction_timeout_seconds
    )


live = pytest.mark.parametrize("provider", _providers(), indirect=True)


def extract(provider, filename: str):
    content = (SAMPLES / filename).read_bytes()
    try:
        return provider.extract(content, filename)
    except TransientProviderError as error:
        pytest.skip(f"{provider.name} is rate limited: {error}")


@live
def test_invoice_extraction(provider):
    """The supplied legal invoice totals 4,680.00 EUR."""
    result = extract(provider, "invoice_legal_services.pdf")

    assert len(result.records) == 1, "an invoice must yield exactly one record"
    record = result.records[0]
    assert record["currency"] == "EUR"
    assert "INV-LX-441" in (record["invoice_number"] or record["reference"] or "")
    assert "4680" in (record["net_amount"] or "").replace(",", "").replace(" ", "")


@live
def test_usage_is_reported(provider):
    """Token accounting must come back, or cost tracking is fiction."""
    result = extract(provider, "invoice_software_subscription.pdf")

    assert result.usage is not None
    assert result.usage.provider == provider.name
    assert result.usage.input_tokens and result.usage.input_tokens > 0
    assert result.usage.duration_ms >= 0


@live
def test_bank_statement_yields_several_records(provider):
    """The supplied statement holds eight transaction rows.

    Asserted as "more than one" rather than "exactly eight" because that is
    what every configured connector can be held to: measured over three runs
    each, OpenAI returned 8, 8, 8 and Gemini 2, 2, 8. The stricter assertion
    lives below, on the primary alone.
    """
    result = extract(provider, "bank_statement_july_2026.pdf")

    assert len(result.records) >= 2, "a statement must not collapse into one record"
    balances = {"323500", "323250", "318570", "319815.35"}
    amounts = {(r["net_amount"] or "").replace(",", "").replace(" ", "") for r in result.records}
    assert not amounts & balances, "running balances were taken instead of line amounts"


@live
def test_no_field_merges_two_cells(provider):
    """The failure that made a statement unusable: two date cells joined into
    one field, as `2026-07-0101/07/2026`."""
    result = extract(provider, "bank_statement_july_2026.pdf")

    for record in result.records:
        for field in ("transaction_date", "value_date"):
            value = record.get(field)
            assert value is None or len(value) <= 10, f"{field} holds two cells: {value!r}"


@live
def test_confidence_is_reported_per_field(provider):
    result = extract(provider, "invoice_legal_services.pdf")

    scores = result.field_confidence[0]
    assert all(0.0 <= value <= 1.0 for value in scores.values())
    assert 0.0 <= record_confidence(scores) <= 1.0


@pytest.mark.skipif(not settings.openai_api_key, reason="OPENAI_API_KEY is not configured")
def test_the_primary_reads_every_statement_row():
    """Held only to the primary, because only it earned this.

    Every row, every reference. The assignment supplies this statement because
    it is the hard document; a provider chosen for reading it must be checked
    against all of it, not against "more than one".
    """
    provider = OpenAIProvider(
        settings.openai_api_key, settings.openai_model, settings.extraction_timeout_seconds
    )
    result = extract(provider, "bank_statement_july_2026.pdf")

    assert len(result.records) == 8
    references = {record.get("reference") for record in result.records}
    assert references == {f"STM-77{n}" for n in range(11, 19)}
