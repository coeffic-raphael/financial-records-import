"""Deterministic provider for tests and offline development.

It exists for three reasons: the test suite must never touch the network, the
application must remain usable without an API key, and the fallback chain needs
something to fall back to when no second real provider is configured.
"""

from typing import Any

from app.providers.base import (
    ExtractionProvider,
    ExtractionResult,
    ExtractionUsage,
    ProviderError,
)


class MockProvider(ExtractionProvider):
    """Returns whatever it was constructed with.

    Tests inject the exact payload a scenario needs -- an incomplete record, a
    low-confidence one, eight statement lines -- without any network call and
    without depending on what a real model happens to answer today.
    """

    name = "mock"

    def __init__(
        self,
        records: list[dict[str, Any]] | None = None,
        field_confidence: list[dict[str, float]] | None = None,
        raises: ProviderError | None = None,
    ) -> None:
        self._records = records if records is not None else []
        self._confidence = field_confidence
        self._raises = raises
        self.calls = 0

    def extract(self, content: bytes, filename: str) -> ExtractionResult:
        self.calls += 1
        if self._raises is not None:
            raise self._raises

        confidence = self._confidence
        if confidence is None:
            confidence = [dict.fromkeys(record, 1.0) for record in self._records]

        return ExtractionResult(
            records=[dict(record) for record in self._records],
            field_confidence=confidence,
            usage=ExtractionUsage(
                provider=self.name, model="mock", duration_ms=0, input_tokens=0, output_tokens=0
            ),
        )
