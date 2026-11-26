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

    # LLM (AI Analyst). The key is server-side only and never logged.
    gemini_api_key: SecretStr | None = Field(default=None, alias="GEMINI_API_KEY")
    gemini_model: str = Field(default="gemini-3.5-flash-lite", alias="WEATHER_RISK_GEMINI_MODEL")
    # Comma-separated fallback chain, tried in order on 503 / timeout / 429 (D-037).
    gemini_fallback_model: str | None = Field(
        default="gemini-3.6-flash,gemini-3.5-flash", alias="WEATHER_RISK_GEMINI_FALLBACK_MODEL"
    )
    # Gemini 3 thinking level ("minimal" | "low" | "medium" | "high"; empty = provider default).
    llm_thinking_level: str | None = Field(default="low", alias="WEATHER_RISK_LLM_THINKING_LEVEL")
    llm_timeout_seconds: float = Field(default=45.0, alias="WEATHER_RISK_LLM_TIMEOUT_SECONDS")
    llm_max_attempts: int = Field(default=3, alias="WEATHER_RISK_LLM_MAX_ATTEMPTS")  # chain rounds
    sessions_path: Path = Field(
        default=PROJECT_ROOT / "data" / "cache" / "sessions.db", alias="WEATHER_RISK_SESSIONS_PATH"
    )
    cors_origins: str = Field(
        default="http://localhost:5173,http://127.0.0.1:5173", alias="WEATHER_RISK_CORS_ORIGINS"
    )

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

    # ---- public-demo protection (Phase 7). Limits <= 0 disable a check. In-memory, per process.
    chat_limit_per_ip_minute: int = Field(default=10, alias="WEATHER_RISK_CHAT_LIMIT_PER_IP_MINUTE")
    chat_limit_per_ip_hour: int = Field(default=60, alias="WEATHER_RISK_CHAT_LIMIT_PER_IP_HOUR")
    chat_limit_per_session_hour: int = Field(
        default=40, alias="WEATHER_RISK_CHAT_LIMIT_PER_SESSION_HOUR"
    )
    chat_daily_limit: int = Field(default=300, alias="WEATHER_RISK_CHAT_DAILY_LIMIT")
    # AI requests run one at a time (the provider keeps per-turn state); others wait in a short queue.
    chat_max_waiting: int = Field(default=4, alias="WEATHER_RISK_CHAT_MAX_WAITING")
    chat_queue_timeout_seconds: float = Field(
        default=30.0, alias="WEATHER_RISK_CHAT_QUEUE_TIMEOUT_SECONDS"
    )
    # Overall budget for one chat turn. Gemini is not called again after it has passed; a turn
    # whose tools already succeeded then returns the labeled deterministic summary.
    chat_deadline_seconds: float = Field(default=60.0, alias="WEATHER_RISK_CHAT_DEADLINE_SECONDS")
    # Reverse proxies in front of the app (Render/Railway: 1). 0 = use the socket peer address.
    trusted_proxy_hops: int = Field(default=0, alias="WEATHER_RISK_TRUSTED_PROXY_HOPS")
    # Optional shared demo password (HTTP Basic auth on everything except /api/health).
    demo_username: str = Field(default="moveo", alias="WEATHER_RISK_DEMO_USERNAME")
    demo_password: SecretStr | None = Field(default=None, alias="WEATHER_RISK_DEMO_PASSWORD")
    # Built frontend served by FastAPI in production (same origin). Ignored if the folder is absent.
    web_dist_dir: Path = Field(default=PROJECT_ROOT / "web" / "dist", alias="WEATHER_RISK_WEB_DIST")
    serve_frontend: bool = Field(default=True, alias="WEATHER_RISK_SERVE_FRONTEND")


@lru_cache
def get_settings() -> Settings:
    return Settings()
