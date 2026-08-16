"""OpenAI connector.

Second provider of the fallback chain. Same contract as Gemini; only the SDK
call differs, which is the point of the interface.
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
from app.providers.schema import EXTRACTION_PROMPT, ExtractionEnvelope, flatten

logger = logging.getLogger(__name__)

PERMANENT_STATUS = {400, 401, 403, 404, 422}


class OpenAIProvider(ExtractionProvider):
    name = "openai"

    def __init__(self, api_key: str, model: str, timeout_seconds: float = 60.0) -> None:
        if not api_key:
            raise ValueError("OPENAI_API_KEY is required to use the OpenAI provider.")
        self._api_key = api_key
        self._model = model
        self._timeout = timeout_seconds
        self._client = None

    def _get_client(self):
        if self._client is None:
            from openai import OpenAI

            self._client = OpenAI(api_key=self._api_key, timeout=self._timeout)
        return self._client

    def extract(self, content: bytes, filename: str) -> ExtractionResult:
        started = time.monotonic()
        encoded = base64.b64encode(content).decode("ascii")
        try:
            response = self._get_client().responses.parse(
                model=self._model,
                input=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "input_file",
                                "filename": filename,
                                "file_data": f"data:application/pdf;base64,{encoded}",
                            },
                            {"type": "input_text", "text": EXTRACTION_PROMPT},
                        ],
                    }
                ],
                text_format=ExtractionEnvelope,
            )
        except Exception as error:  # noqa: BLE001 -- mapped to the provider contract below
            raise self._translate(error) from error

        duration_ms = int((time.monotonic() - started) * 1000)

        envelope = response.output_parsed
        if envelope is None:
            raise InvalidProviderResponseError(
                "OpenAI returned no parsable payload for the extraction schema."
            )

        records, confidence = flatten(envelope)
        logger.info(
            "Extraction succeeded: provider=%s model=%s records=%s duration_ms=%s",
            self.name, self._model, len(records), duration_ms,
        )
        usage = getattr(response, "usage", None)
        return ExtractionResult(
            records=records,
            field_confidence=confidence,
            usage=ExtractionUsage(
                provider=self.name,
                model=self._model,
                duration_ms=duration_ms,
                input_tokens=getattr(usage, "input_tokens", None),
                output_tokens=getattr(usage, "output_tokens", None),
            ),
        )

    @staticmethod
    def _translate(error: Exception) -> Exception:
        status = getattr(error, "status_code", None) or getattr(error, "code", None)
        if isinstance(status, int) and status in PERMANENT_STATUS:
            return PermanentProviderError(f"OpenAI rejected the request (HTTP {status}).")
        return TransientProviderError(f"OpenAI call failed: {type(error).__name__}")
