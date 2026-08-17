"""Deterministic provider for tests and offline development.

Two reasons, both real. The default test suite must never touch the network --
it would be slow, billable, and dependent on what a model answers today. And
the application must stay usable with no API key at all, which is what makes a
clean clone runnable: the image ships with EXTRACTION_PROVIDER=mock.

It is NOT a terminus of the fallback chain. `build_provider` never appends it:
with a single real provider configured, that provider is returned alone, and a
failure surfaces as a failure rather than as silently canned data.
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
