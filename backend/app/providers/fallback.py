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
        # Every failure is kept, not just the last one. Reporting only the final
        # error hid WHY the primary provider gave up: a chain that ends on the
        # fallback's rate limit says nothing about the provider that actually
        # mattered.
        failures: list[str] = []

        for provider in self._providers:
            for attempt in range(1, self._attempts + 1):
                try:
                    return provider.extract(content, filename)
                except TransientProviderError as error:
                    failures.append(f"{provider.name}: {error}")
                    # Never log the document or the payload: financial data.
                    logger.warning(
                        "Extraction attempt %s/%s failed on %s: %s",
                        attempt, self._attempts, provider.name, type(error).__name__,
                    )
                except PermanentProviderError as error:
                    failures.append(f"{provider.name}: {error}")
                    logger.warning(
                        "Provider %s failed permanently: %s", provider.name, type(error).__name__
                    )
                    break

        # De-duplicated: retrying one provider twice should not say the same
        # thing twice in a message someone has to read.
        distinct = list(dict.fromkeys(failures))
        raise ProviderError("Every provider failed. " + " | ".join(distinct))
