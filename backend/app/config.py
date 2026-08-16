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

    # Uploaded documents are kept so a reviewer can check an extraction against
    # its source. Outside any served directory: nothing here is reachable except
    # through the tenant-scoped endpoint.
    upload_storage_dir: str = "./uploads"

    # --- Authentication ---
    debug: bool = False
    jwt_secret: str = ""
    jwt_algorithm: str = "HS256"

    # Short-lived on purpose: it is what makes an access-token denylist
    # unnecessary. Revocation happens on the refresh token, which is stateful.
    access_token_ttl_minutes: int = 15
    refresh_token_ttl_days: int = 14

    # Secure cookies are never sent over http://localhost, so a development run
    # would fail authentication with no visible reason. Driven by config; the
    # other two attributes are unconditional.
    cookie_secure: bool = True
    refresh_cookie_name: str = "refresh_token"

    # --- AI extraction ---
    # None of these may carry a VITE_ prefix: any VITE_* variable is compiled
    # into the browser bundle. Extraction is server-side only; the frontend
    # never learns which provider is used.
    extraction_provider: str = "gemini"
    gemini_api_key: str = ""
    openai_api_key: str = ""
    # Verified against the supplied documents. Newer flash models exist, but
    # carry no free-tier quota on a personal key: every extraction comes back
    # 429 and the feature looks broken rather than unfunded.
    gemini_model: str = "gemini-3.5-flash"
    openai_model: str = "gpt-5.6"
    # Measured, not guessed: the supplied bank statement takes ~135 s to come
    # back as eight records, where a one-record invoice takes ~25 s. A 60 s
    # timeout aborted the statement every time -- the one document in the set
    # that exercises multi-record extraction.
    extraction_timeout_seconds: float = 180.0
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
