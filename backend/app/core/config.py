"""
Central application configuration.
All settings are loaded from environment variables / .env file.
Never hard-code credentials here.
"""

from __future__ import annotations

import os
from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Environment ───────────────────────────────────────────
    environment: Literal["development", "production", "testing"] = "production"

    @property
    def is_development(self) -> bool:
        return self.environment == "development"

    @property
    def is_testing(self) -> bool:
        return self.environment == "testing"

    # ── Bot ───────────────────────────────────────────────────
    bot_token: str = Field(..., description="Telegram Bot API token from BotFather")
    bot_username: str = Field(default="", description="Bot @username (without @)")
    telegram_api_version: str = "10.3"  # Current as of 2026-08-24

    # ── Admins ───────────────────────────────────────────────
    admin_ids: str = Field(default="", description="Comma-separated admin Telegram user IDs")

    @property
    def admin_id_list(self) -> list[int]:
        if not self.admin_ids:
            return []
        return [int(x.strip()) for x in self.admin_ids.split(",") if x.strip().isdigit()]

    # ── Database ─────────────────────────────────────────────
    database_url: str = Field(
        default="sqlite+aiosqlite:///./publisher.db",
        description="Async SQLAlchemy database URL",
    )

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")

    # ── Redis / Queue ────────────────────────────────────────
    redis_url: str = Field(default="redis://localhost:6379/0")
    celery_broker_url: str = Field(default="redis://localhost:6379/1")
    celery_result_backend: str = Field(default="redis://localhost:6379/2")

    # ── API / Web ────────────────────────────────────────────
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    secret_key: str = Field(default="CHANGE_ME_IN_PRODUCTION_USE_64_RANDOM_HEX_CHARS")
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 1440  # 24 hours
    refresh_token_expire_days: int = 30

    # ── Webhook ──────────────────────────────────────────────
    webhook_url: str = Field(default="", description="HTTPS URL for Telegram webhook")
    webhook_secret: str = Field(default="", description="Webhook secret token")
    webhook_path: str = "/webhook"

    @property
    def use_webhook(self) -> bool:
        return bool(self.webhook_url)

    # ── AI ───────────────────────────────────────────────────
    ai_provider: Literal["openai", "anthropic", "none"] = "none"
    openai_api_key: str = ""
    anthropic_api_key: str = ""
    ai_model: str = "gpt-4o-mini"
    ai_max_tokens: int = 2000

    # ── Storage ──────────────────────────────────────────────
    storage_provider: Literal["local", "s3"] = "local"
    local_media_path: str = "./media"
    aws_access_key_id: str = ""
    aws_secret_access_key: str = ""
    aws_s3_bucket: str = ""
    aws_s3_region: str = "us-east-1"

    # ── Scheduling ───────────────────────────────────────────
    default_timezone: str = "Africa/Addis_Ababa"
    max_retry_attempts: int = 5
    retry_base_delay: float = 2.0  # seconds, for exponential backoff

    # ── Rate limiting ────────────────────────────────────────
    # Telegram limits: 1 msg/sec per chat, 20 msg/min per group, ~30/sec global
    rate_limit_per_chat_per_second: float = 0.9
    rate_limit_per_group_per_minute: int = 18
    rate_limit_global_per_second: int = 25
    rate_limit_burst_capacity: int = 10

    # ── Feature flags ────────────────────────────────────────
    feature_ai: bool = False
    feature_analytics: bool = True
    feature_mini_app: bool = False
    feature_automation: bool = True
    feature_inline: bool = True
    feature_campaigns: bool = True
    feature_ab_testing: bool = False
    feature_monitoring: bool = False
    feature_rich_messages: bool = True    # Bot API 10.1+
    feature_ephemeral: bool = False       # Bot API 10.2+
    feature_communities: bool = False     # Bot API 10.2+
    feature_guest_mode: bool = False      # Bot API 10.0+

    # ── Safety ───────────────────────────────────────────────
    dry_run: bool = False
    log_level: str = "INFO"

    # ── Pagination ───────────────────────────────────────────
    default_page_size: int = 50
    max_page_size: int = 200

    @field_validator("secret_key")
    @classmethod
    def validate_secret_key(cls, v: str) -> str:
        if v == "CHANGE_ME_IN_PRODUCTION_USE_64_RANDOM_HEX_CHARS":
            import warnings
            warnings.warn(
                "SECRET_KEY is set to the default placeholder. "
                "Generate a secure key for production.",
                stacklevel=2,
            )
        return v

    @field_validator("bot_token")
    @classmethod
    def validate_bot_token(cls, v: str) -> str:
        if ":" not in v:
            raise ValueError("BOT_TOKEN appears invalid (missing ':' separator)")
        return v


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the cached application settings singleton."""
    return Settings()


# Convenience alias
settings = get_settings()
