"""Provider chain.

Implements the same interface as the providers it wraps, so it is substitutable
for any of them and testable with two doubles.
"""

import logging

from app.providers.base import (
    ExtractionProvider,
    ExtractionResult,
    PermanentProviderError,
    ProviderError,
    TransientProviderError,
)

logger = logging.getLogger(__name__)


class FallbackProvider(ExtractionProvider):
    """Tries each provider in order until one returns a result.

    Both failure kinds move to the next provider, but only transient ones are
    retried on the SAME provider first. Retrying a permanent error -- bad key,
    unknown model -- cannot succeed; it only burns quota and delays the
    fallback.
    """

    name = "fallback"

    def __init__(self, providers: list[ExtractionProvider], attempts_per_provider: int = 2) -> None:
        if not providers:
            raise ValueError("A fallback chain needs at least one provider.")
        self._providers = providers
        self._attempts = max(1, attempts_per_provider)

    @property
    def chain(self) -> list[str]:
        return [provider.name for provider in self._providers]

    def extract(self, content: bytes, filename: str) -> ExtractionResult:
        last_error: ProviderError | None = None

        for provider in self._providers:
            for attempt in range(1, self._attempts + 1):
                try:
                    return provider.extract(content, filename)
                except TransientProviderError as error:
                    last_error = error
                    # Never log the document or the payload: financial data.
                    logger.warning(
                        "Extraction attempt %s/%s failed on %s: %s",
                        attempt, self._attempts, provider.name, type(error).__name__,
                    )
                except PermanentProviderError as error:
                    last_error = error
                    logger.warning(
                        "Provider %s failed permanently: %s", provider.name, type(error).__name__
                    )
                    break

        raise ProviderError(
            f"Every provider in the chain failed ({', '.join(self.chain)}): {last_error}"
        ) from last_error
