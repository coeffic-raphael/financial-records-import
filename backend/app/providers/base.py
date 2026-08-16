"""Provider interface.

Everything the application knows about an AI provider is this file. Concrete
implementations, the fallback chain and the test double all satisfy the same
contract, which is what makes the provider swappable and the test suite
hermetic.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


class ProviderError(Exception):
    """Any failure to obtain a usable extraction."""


class TransientProviderError(ProviderError):
    """Worth retrying, and worth falling through to the next provider.

    Timeouts, rate limits, 5xx.
    """


class PermanentProviderError(ProviderError):
    """Retrying will not help: bad credentials, malformed request, unknown model.

    Retrying these only burns quota and delays the fallback, so the chain moves
    on immediately.
    """


class InvalidProviderResponseError(PermanentProviderError):
    """The call succeeded but the payload is unusable: bad JSON, wrong shape.

    Distinct because it says something about the prompt or the schema rather
    than about the connection.
    """


@dataclass(frozen=True, slots=True)
class ExtractionUsage:
    provider: str
    model: str
    duration_ms: int
    input_tokens: int | None = None
    output_tokens: int | None = None


@dataclass(frozen=True, slots=True)
class ExtractionResult:
    """One document's worth of extraction.

    `records` holds raw values, shaped exactly like a CSV row, so they flow into
    the same normalization and validation as every other source. No PDF-specific
    validation exists anywhere in this codebase, and that is deliberate.
    """

    records: list[dict[str, Any]] = field(default_factory=list)
    field_confidence: list[dict[str, float]] = field(default_factory=list)
    usage: ExtractionUsage | None = None


class ExtractionProvider(ABC):
    """A source of structured records from a document.

    `extract` is SYNCHRONOUS on purpose. These calls run inside background
    tasks; an async def wrapping a blocking SDK would occupy the event loop and
    freeze every other request for the duration of the extraction -- exactly the
    problem background processing exists to avoid. A sync function is dispatched
    to the thread pool instead.
    """

    name: str = "provider"

    @abstractmethod
    def extract(self, content: bytes, filename: str) -> ExtractionResult:
        """Return records found in the document.

        Raises TransientProviderError or PermanentProviderError. It must never
        raise anything else: the caller turns these into a failed job, and an
        unexpected exception type would escape that handling.
        """
