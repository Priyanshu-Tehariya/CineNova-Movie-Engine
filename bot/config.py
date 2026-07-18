from __future__ import annotations

import json
from typing import List

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Encapsulates system configuration parameters loaded dynamically via environmental state contexts."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
    )

    # ── Bot Configuration ───────────────────────────────────────────────────
    BOT_TOKEN: str
    BOT_USERNAME: str  # Format validation: without administrative '@' prefix

    # ── Access Access Matrix ────────────────────────────────────────────────
    ADMIN_IDS: List[int] = []

    # ── Infrastructure Storage Nodes ────────────────────────────────────────
    STORAGE_CHANNEL_ID: int
    
    # ── Operational Logs ────────────────────────────────────────────────────
    LOG_CHANNEL_ID: int  

    # ── Request Validation Dashboard Nodes ─────────────────────────────────
    REQUEST_CHANNEL_ID: int

    # ── Dynamic Subscription Constraints ────────────────────────────────────
    FORCE_JOIN_CHANNELS: List[str] = []
    FORCE_JOIN_CACHE_TTL: int = 3600  # Duration expressed in baseline seconds

    # ── Relational Database Infrastructure ──────────────────────────────────
    DATABASE_URL: str
    DB_POOL_SIZE: int = 20
    DB_MAX_OVERFLOW: int = 10
    DB_POOL_TIMEOUT: int = 30

    # ── Distributed Caching Parameters ──────────────────────────────────────
    REDIS_URL: str = "redis://localhost:6379/0"
    REDIS_MAX_CONNECTIONS: int = 50

    # ── Asset Lifecycle Auto-Destruction ────────────────────────────────────
    AUTO_DELETE_TIMEOUT: int = 600        # Interval constraint until resource erasure
    AUTO_DELETE_WARNING_TIME: int = 60    # Alert notification window leading up to erasure

    # ── Rate Limiting Traffic Management ────────────────────────────────────
    RATE_LIMIT_MESSAGES: int = 5
    RATE_LIMIT_WINDOW: int = 10  # Expressed in operational sliding seconds

    # ── Full Text Search Buffering ──────────────────────────────────────────
    SEARCH_CACHE_TTL: int = 300
    MAX_SEARCH_RESULTS: int = 8

    # ── Analytical Logging Instrumentation ──────────────────────────────────
    LOG_LEVEL: str = "INFO"
    LOG_JSON: bool = True

    @field_validator("ADMIN_IDS", "FORCE_JOIN_CHANNELS", mode="before")
    @classmethod
    def _parse_list(cls, v: object) -> list:
        """Parses variant environment string formats or JSON structures down to standard sequence lists."""
        if isinstance(v, list):
            return [str(item) for item in v]
        if isinstance(v, (int, float)):
            return [str(v)]
        if isinstance(v, str):
            v = v.strip()
            if v.startswith("[") and v.endswith("]"):
                try:
                    parsed = json.loads(v)
                    if isinstance(parsed, list):
                        return [str(item) for item in parsed]
                except json.JSONDecodeError:
                    pass
            return [item.strip() for item in v.split(",") if item.strip()]
        return v


settings = Settings()