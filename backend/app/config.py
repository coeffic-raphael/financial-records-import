"""Application settings, read once at startup.

Single source of configuration: no scattered `os.getenv`. A missing required
variable stops the application from starting rather than failing on the first
request that needs it.
"""

from decimal import Decimal
from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # No default on purpose. A default would silently point a misconfigured
    # deployment at the wrong database; being unable to start is the better
    # failure. Note this only catches an ABSENT url: create_engine() is lazy, so
    # an unreachable one surfaces on the first connection -- in the container
    # that is `alembic upgrade head`, which runs before uvicorn.
    # min_length rather than a bare `str`: an empty DATABASE_URL= line in a .env
    # satisfies a required string, and this project has already been bitten by
    # exactly that with JWT_SECRET.
    database_url: str = Field(min_length=1)

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
    extraction_provider: str = "openai"
    gemini_api_key: str = ""
    openai_api_key: str = ""
    # The OpenAI model is PINNED to an exact build, not to a floating alias.
    # "gpt-5.6" is an alias: it resolves to gpt-5.6-sol today and may point
    # somewhere else tomorrow, which would change extraction behaviour with no
    # code change and silently invalidate the measurement in the README.
    #
    # Gemini offers no dated build for this tier -- gemini-3.5-flash is the only
    # name there is -- so the fallback cannot be pinned the same way, and its
    # behaviour can shift under us. It is the fallback, not the primary, which
    # is what makes that acceptable rather than merely unavoidable.
    #
    # gpt-5.4-mini was measured against gpt-5.6-sol on the supplied bank
    # statement -- the hardest document in the set, a dense six-column table.
    # Both read all eight rows correctly, twice, with every reference, amount,
    # date and currency right. mini did it in 9-15 s against 26-27 s, and costs
    # $0.0096 per statement against $0.0785: eight times less for the same
    # result, so the expensive tier buys nothing measurable here.
    gemini_model: str = "gemini-3.5-flash"
    openai_model: str = "gpt-5.4-mini-2026-03-17"
    # Sized for the SLOWEST provider in the chain, not the primary. The pinned
    # OpenAI model answers the statement in 9-15 s, but Gemini has taken 140 s
    # on the same document, and a timeout below that turns a slow fallback into
    # a failed import.
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
