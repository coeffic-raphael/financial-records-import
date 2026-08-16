"""Fallback chain behaviour, with two doubles and no network."""

import pytest

from app.providers.base import (
    PermanentProviderError,
    ProviderError,
    TransientProviderError,
)
from app.providers.fallback import FallbackProvider
from app.providers.mock import MockProvider

RECORD = {"reference": "R-1", "gross_amount": "100.00"}


class TestChaining:
    def test_first_provider_wins_when_it_succeeds(self):
        primary = MockProvider(records=[RECORD])
        secondary = MockProvider(records=[])
        chain = FallbackProvider([primary, secondary])

        result = chain.extract(b"pdf", "x.pdf")

        assert result.records == [RECORD]
        assert secondary.calls == 0, "the second provider must not be called needlessly"

    def test_falls_through_when_the_first_fails(self):
        primary = MockProvider(raises=TransientProviderError("timeout"))
        secondary = MockProvider(records=[RECORD])

        result = FallbackProvider([primary, secondary]).extract(b"pdf", "x.pdf")

        assert result.records == [RECORD]
        assert secondary.calls == 1

    def test_raises_when_every_provider_fails(self):
        chain = FallbackProvider(
            [
                MockProvider(raises=TransientProviderError("timeout")),
                MockProvider(raises=TransientProviderError("timeout")),
            ]
        )
        with pytest.raises(ProviderError, match="Every provider failed"):
            chain.extract(b"pdf", "x.pdf")

    def test_the_message_names_every_provider_that_failed(self):
        """Reporting only the last error hid why the PRIMARY provider gave up.

        A chain ending on the fallback's rate limit says nothing about the one
        that actually mattered.
        """
        chain = FallbackProvider(
            [
                MockProvider(raises=TransientProviderError("gemini quota exhausted")),
                MockProvider(raises=TransientProviderError("openai has no credit")),
            ]
        )

        with pytest.raises(ProviderError) as raised:
            chain.extract(b"pdf", "x.pdf")

        assert "gemini quota exhausted" in str(raised.value)
        assert "openai has no credit" in str(raised.value)

    def test_a_retried_failure_is_reported_once(self):
        chain = FallbackProvider(
            [MockProvider(raises=TransientProviderError("timeout"))], attempts_per_provider=3
        )

        with pytest.raises(ProviderError) as raised:
            chain.extract(b"pdf", "x.pdf")

        assert str(raised.value).count("timeout") == 1

    def test_an_empty_chain_is_rejected_at_construction(self):
        with pytest.raises(ValueError, match="at least one provider"):
            FallbackProvider([])


class TestRetryPolicy:
    """Retrying is only ever useful for a transient failure."""

    def test_transient_errors_are_retried_on_the_same_provider(self):
        primary = MockProvider(raises=TransientProviderError("rate limited"))
        chain = FallbackProvider([primary, MockProvider(records=[RECORD])], attempts_per_provider=3)

        chain.extract(b"pdf", "x.pdf")

        assert primary.calls == 3

    def test_permanent_errors_are_never_retried(self):
        """A bad key or an unknown model cannot improve on a second attempt.

        Retrying would only burn quota and delay the fallback.
        """
        primary = MockProvider(raises=PermanentProviderError("invalid api key"))
        secondary = MockProvider(records=[RECORD])
        chain = FallbackProvider([primary, secondary], attempts_per_provider=3)

        chain.extract(b"pdf", "x.pdf")

        assert primary.calls == 1
        assert secondary.calls == 1
