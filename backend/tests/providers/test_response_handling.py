"""What a connector does with what the provider actually sends back.

The chain tests inject exceptions into a double, so they prove the chain and
never touch the code that decodes a real response. This file covers that code:
a malformed payload, an empty one, a well-formed JSON of the wrong shape, and
an SDK exception that must be classified before the chain can decide whether
retrying is worth anything.

The requirement is that none of these crash the application. They must all
arrive as `ProviderError`, which is the only failure the rest of the code
knows how to handle.
"""

import pytest

from app.providers.base import (
    InvalidProviderResponseError,
    PermanentProviderError,
    ProviderError,
    TransientProviderError,
)
from app.providers.gemini import GeminiProvider
from app.providers.openai import OpenAIProvider

PDF = b"%PDF-1.7\n" + b"x" * 32


class FakeResponse:
    def __init__(self, output_text=None, output_parsed=None):
        self.output_text = output_text
        self.output_parsed = output_parsed
        self.usage = None


class FakeGeminiClient:
    """Stands in for `genai.Client`, answering whatever a test needs."""

    def __init__(self, response=None, error=None):
        self._response, self._error = response, error
        self.interactions = self

    def create(self, **_kwargs):
        if self._error is not None:
            raise self._error
        return self._response


class FakeOpenAIClient:
    def __init__(self, response=None, error=None):
        self._response, self._error = response, error
        self.responses = self

    def parse(self, **_kwargs):
        if self._error is not None:
            raise self._error
        return self._response


def gemini_returning(text):
    provider = GeminiProvider(api_key="test-key", model="test-model")
    provider._client = FakeGeminiClient(response=FakeResponse(output_text=text))
    return provider


def gemini_raising(error):
    provider = GeminiProvider(api_key="test-key", model="test-model")
    provider._client = FakeGeminiClient(error=error)
    return provider


class TestAPayloadThatIsNotUsable:
    @pytest.mark.parametrize(
        ("label", "payload"),
        [
            ("not json at all", "I could not read this document, sorry."),
            ("truncated json", '{"records": [{"reference": {"value": "TX-1"'),
            ("json but not an object", "[1, 2, 3]"),
            ("empty string", ""),
            ("nothing at all", None),
            ("records is not a list", '{"records": "none"}'),
            ("a record is not an object", '{"records": ["TX-1"]}'),
            ("markdown-fenced json", '```json\n{"records": []}\n```'),
        ],
    )
    def test_it_becomes_a_provider_error_rather_than_an_exception(self, label, payload):
        """Every one of these is a payload a model can genuinely produce."""
        with pytest.raises(InvalidProviderResponseError):
            gemini_returning(payload).extract(PDF, "invoice.pdf")

    def test_the_message_does_not_echo_the_payload(self):
        """A provider's answer can contain document content; it is not for logs."""
        secret = '{"records": "IBAN FR76 3000 1000 0100 0000 1234 567"}'
        with pytest.raises(ProviderError) as raised:
            gemini_returning(secret).extract(PDF, "invoice.pdf")
        assert "FR76" not in str(raised.value)


class TestAPayloadThatIsUsableButEmpty:
    def test_an_empty_extraction_is_a_success_with_no_records(self):
        """Not an error: a document may genuinely hold no transaction.

        The distinction matters -- an empty result is persisted as an
        extraction that found nothing, while a broken payload must fail the
        job rather than silently look like an empty document.
        """
        result = gemini_returning('{"records": []}').extract(PDF, "invoice.pdf")
        assert result.records == []

    def test_a_record_with_every_field_null_still_comes_through(self):
        """Incomplete extraction is the domain's problem, not the connector's."""
        result = gemini_returning(
            '{"records": [{"reference": {"value": null, "confidence": 0.0}}]}'
        ).extract(PDF, "invoice.pdf")
        assert len(result.records) == 1


class TestAnSdkFailureIsClassified:
    @pytest.mark.parametrize("code", [400, 401, 403, 404, 422])
    def test_a_refusal_is_permanent(self, code):
        """Retrying a bad key or an unknown model only delays the fallback."""
        error = Exception("refused")
        error.code = code
        with pytest.raises(PermanentProviderError):
            gemini_raising(error).extract(PDF, "invoice.pdf")

    @pytest.mark.parametrize("code", [429, 500, 502, 503])
    def test_an_overload_is_transient(self, code):
        error = Exception("busy")
        error.code = code
        with pytest.raises(TransientProviderError):
            gemini_raising(error).extract(PDF, "invoice.pdf")

    def test_an_unrecognised_failure_is_transient(self):
        """Unknown means unknown: falling through beats failing the upload."""
        with pytest.raises(TransientProviderError):
            gemini_raising(TimeoutError("connection reset")).extract(PDF, "invoice.pdf")

    def test_the_message_names_the_provider(self):
        """The chain reports every link, so each message must identify itself."""
        with pytest.raises(ProviderError) as raised:
            gemini_raising(TimeoutError("boom")).extract(PDF, "invoice.pdf")
        assert "Gemini" in str(raised.value)


class TestTheOtherConnectorBehavesTheSame:
    def test_an_unparsable_response_is_an_invalid_response(self):
        provider = OpenAIProvider(api_key="test-key", model="test-model")
        provider._client = FakeOpenAIClient(response=FakeResponse(output_parsed=None))
        with pytest.raises(InvalidProviderResponseError):
            provider.extract(PDF, "invoice.pdf")

    def test_a_refusal_is_permanent(self):
        error = Exception("refused")
        error.status_code = 401
        provider = OpenAIProvider(api_key="test-key", model="test-model")
        provider._client = FakeOpenAIClient(error=error)
        with pytest.raises(PermanentProviderError):
            provider.extract(PDF, "invoice.pdf")
