"""Google Gemini connector.

The SDK shape used here was verified against the current documentation and a
real call, not recalled: the API is `client.interactions.create`, the schema
goes in `response_format`, and usage arrives on `response.usage`.
"""

import base64
import logging
import time

from app.providers.base import (
    ExtractionProvider,
    ExtractionResult,
    ExtractionUsage,
    InvalidProviderResponseError,
    PermanentProviderError,
    TransientProviderError,
)
from app.providers.schema import (
    EXTRACTION_PROMPT,
    ExtractionEnvelope,
    flatten,
    json_schema,
)

logger = logging.getLogger(__name__)

# 4xx that will not improve on retry. Anything else is treated as transient.
PERMANENT_STATUS = {400, 401, 403, 404, 422}


class GeminiProvider(ExtractionProvider):
    name = "gemini"

    def __init__(self, api_key: str, model: str, timeout_seconds: float = 60.0) -> None:
        if not api_key:
            raise ValueError("GEMINI_API_KEY is required to use the Gemini provider.")
        self._api_key = api_key
        self._model = model
        self._timeout = timeout_seconds
        self._client = None

    def _get_client(self):
        # Built lazily so that importing the module never requires credentials.
        if self._client is None:
            from google import genai
            from google.genai import types

            # The SDK expects milliseconds. Without this the configured timeout
            # was stored and never applied, so a hung call would have held a
            # semaphore slot until the SDK's own default expired.
            self._client = genai.Client(
                api_key=self._api_key,
                http_options=types.HttpOptions(timeout=int(self._timeout * 1000)),
            )
        return self._client

    def extract(self, content: bytes, filename: str) -> ExtractionResult:
        started = time.monotonic()
        try:
            response = self._get_client().interactions.create(
                model=self._model,
                input=[
                    {
                        "type": "document",
                        "data": base64.b64encode(content).decode("ascii"),
                        "mime_type": "application/pdf",
                    },
                    {"type": "text", "text": EXTRACTION_PROMPT},
                ],
                response_format={
                    "type": "text",
                    "mime_type": "application/json",
                    "schema": json_schema(),
                },
            )
        except Exception as error:  # noqa: BLE001 -- mapped to the provider contract below
            raise self._translate(error) from error

        duration_ms = int((time.monotonic() - started) * 1000)

        # The payload is validated BEFORE anything reaches the database. A
        # response that does not fit the schema is rejected here, never stored.
        try:
            envelope = ExtractionEnvelope.model_validate_json(response.output_text or "")
        except Exception as error:  # noqa: BLE001 -- includes json and validation failures
            raise InvalidProviderResponseError(
                "Gemini returned a payload that does not match the extraction schema."
            ) from error

        records, confidence = flatten(envelope)
        logger.info(
            "Extraction succeeded: provider=%s model=%s records=%s duration_ms=%s",
            self.name, self._model, len(records), duration_ms,
        )
        return ExtractionResult(
            records=records,
            field_confidence=confidence,
            usage=self._usage(response, duration_ms),
        )

    def _usage(self, response, duration_ms: int) -> ExtractionUsage:
        usage = getattr(response, "usage", None)
        return ExtractionUsage(
            provider=self.name,
            model=self._model,
            duration_ms=duration_ms,
            input_tokens=getattr(usage, "total_input_tokens", None),
            # Reasoning tokens are billed, so they belong in the output count
            # rather than being quietly dropped.
            output_tokens=(getattr(usage, "total_output_tokens", 0) or 0)
            + (getattr(usage, "total_thought_tokens", 0) or 0)
            if usage is not None
            else None,
        )

    @staticmethod
    def _translate(error: Exception) -> Exception:
        """Map an SDK exception onto the provider contract.

        The distinction matters: a permanent error must not be retried, because
        retrying cannot help and only delays the fallback.
        """
        status = getattr(error, "code", None) or getattr(error, "status_code", None)
        if isinstance(status, int) and status in PERMANENT_STATUS:
            return PermanentProviderError(f"Gemini rejected the request (HTTP {status}).")
        return TransientProviderError(f"Gemini call failed: {type(error).__name__}")
