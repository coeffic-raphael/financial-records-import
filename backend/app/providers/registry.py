"""Builds the provider from configuration.

Selection lives in one place so that no other module has to know which provider
is configured -- including the frontend, which never learns it at all.
"""

import logging

from app.config import Settings
from app.providers.base import ExtractionProvider
from app.providers.fallback import FallbackProvider
from app.providers.gemini import GeminiProvider
from app.providers.mock import MockProvider
from app.providers.openai import OpenAIProvider

logger = logging.getLogger(__name__)


def build_provider(settings: Settings) -> ExtractionProvider:
    """Return the provider named by configuration.

    `gemini` and `openai` build a chain when the other key is also present, so a
    transient failure on the primary falls through instead of failing the job.
    `mock` keeps the application usable with no credentials at all.

    A missing key for an explicitly requested provider raises HERE, at startup,
    rather than on the first upload: an application that cannot extract should
    say so before a user hands it a document.
    """
    choice = (settings.extraction_provider or "").strip().lower()

    if choice == "mock":
        return MockProvider()

    if choice == "gemini":
        chain: list[ExtractionProvider] = [
            GeminiProvider(
                settings.gemini_api_key, settings.gemini_model, settings.extraction_timeout_seconds
            )
        ]
        if settings.openai_api_key:
            chain.append(
                OpenAIProvider(
                    settings.openai_api_key,
                    settings.openai_model,
                    settings.extraction_timeout_seconds,
                )
            )
        return chain[0] if len(chain) == 1 else FallbackProvider(chain)

    if choice == "openai":
        chain = [
            OpenAIProvider(
                settings.openai_api_key, settings.openai_model, settings.extraction_timeout_seconds
            )
        ]
        if settings.gemini_api_key:
            chain.append(
                GeminiProvider(
                    settings.gemini_api_key,
                    settings.gemini_model,
                    settings.extraction_timeout_seconds,
                )
            )
        return chain[0] if len(chain) == 1 else FallbackProvider(chain)

    raise ValueError(
        f"Unknown EXTRACTION_PROVIDER {settings.extraction_provider!r}. "
        "Expected one of: gemini, openai, mock."
    )
