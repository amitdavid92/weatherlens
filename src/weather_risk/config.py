"""Application settings, loaded from environment variables / a local `.env` file.

Secrets are typed as `SecretStr` so they are redacted in repr() and logs.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # LLM — declared for later phases; unused in the data layer.
    gemini_api_key: SecretStr | None = Field(default=None, alias="GEMINI_API_KEY")

    cache_path: Path = Field(
        default=PROJECT_ROOT / "data" / "cache" / "cache.db", alias="WEATHER_RISK_CACHE_PATH"
    )
    snapshot_dir: Path = Field(
        default=PROJECT_ROOT / "data" / "snapshot", alias="WEATHER_RISK_SNAPSHOT_DIR"
    )
    hubs_path: Path = Field(
        default=PROJECT_ROOT / "config" / "hubs.yaml", alias="WEATHER_RISK_HUBS_PATH"
    )

    ttl_historical_seconds: int = Field(
        default=30 * 24 * 3600, alias="WEATHER_RISK_TTL_HISTORICAL_SECONDS"
    )
    ttl_recent_seconds: int = Field(default=24 * 3600, alias="WEATHER_RISK_TTL_RECENT_SECONDS")
    ttl_nri_seconds: int = Field(default=7 * 24 * 3600, alias="WEATHER_RISK_TTL_NRI_SECONDS")

    http_timeout_seconds: float = Field(default=30.0, alias="WEATHER_RISK_HTTP_TIMEOUT_SECONDS")
    http_max_attempts: int = Field(default=3, alias="WEATHER_RISK_HTTP_MAX_ATTEMPTS")

    # Offline mode: never call external APIs; serve cache (fresh or stale) and snapshot only.
    offline: bool = Field(default=False, alias="WEATHER_RISK_OFFLINE")

    log_level: str = Field(default="INFO", alias="LOG_LEVEL")


@lru_cache
def get_settings() -> Settings:
    return Settings()
