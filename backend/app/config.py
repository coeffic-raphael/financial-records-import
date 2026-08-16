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
    extraction_confidence_threshold: Decimal = Decimal("0.70")

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_allowed_origins.split(",") if origin.strip()]

    def __repr__(self) -> str:
        """Never reveal secrets through an accidental print or log line."""
        return f"Settings(database_url={self._mask(self.database_url)!r}, ...)"

    @staticmethod
    def _mask(value: str) -> str:
        return value if "@" not in value else "***"


@lru_cache
def get_settings() -> Settings:
    return Settings()
