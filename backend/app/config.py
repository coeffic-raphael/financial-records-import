"""Application settings, read once at startup.

Single source of configuration: no scattered `os.getenv`. A missing required
variable stops the application from starting rather than failing on the first
request that needs it.
"""

from decimal import Decimal
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "sqlite:///./financial_records.db"

    # Explicit origins are mandatory: browsers forbid "*" together with credentials.
    cors_allowed_origins: str = "http://localhost:5173"

    max_upload_bytes: int = 10 * 1024 * 1024

    # --- AI extraction ---
    # None of these may carry a VITE_ prefix: any VITE_* variable is compiled
    # into the browser bundle. Extraction is server-side only; the frontend
    # never learns which provider is used.
    extraction_provider: str = "gemini"
    gemini_api_key: str = ""
    openai_api_key: str = ""
    gemini_model: str = "gemini-3.6-flash"
    openai_model: str = "gpt-5.6"
    extraction_timeout_seconds: float = 60.0
    extraction_confidence_threshold: Decimal = Decimal("0.70")

    # The thread pool would happily run dozens of extractions at once, but free
    # provider quotas are counted in requests per minute. The slowest component
    # sets the limit, not the fastest.
    max_concurrent_extractions: int = 3

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_allowed_origins.split(",") if origin.strip()]

    def __repr__(self) -> str:
        """Never reveal secrets through an accidental print or log line."""
        return (
            f"Settings(database_url={self._mask(self.database_url)!r}, "
            f"extraction_provider={self.extraction_provider!r}, "
            f"gemini_api_key={'set' if self.gemini_api_key else 'unset'}, "
            f"openai_api_key={'set' if self.openai_api_key else 'unset'})"
        )

    @staticmethod
    def _mask(value: str) -> str:
        return value if "@" not in value else "***"


@lru_cache
def get_settings() -> Settings:
    return Settings()
