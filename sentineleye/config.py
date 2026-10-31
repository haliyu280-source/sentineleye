"""Central configuration. Every setting can be overridden with a SENTINELEYE_* environment variable."""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SENTINELEYE_", env_file=".env", extra="ignore")

    database_url: str = "sqlite:///./data/sentineleye.db"

    # Bearer token for the management API. Left unset, management endpoints refuse every request.
    admin_token: str | None = None

    # Availability
    heartbeat_timeout_seconds: int = Field(90, ge=10)
    background_interval_seconds: int = Field(15, ge=1)
    run_background_jobs: bool = True

    # Alerting
    alert_consecutive_breaches: int = Field(2, ge=1, le=20)
    default_cpu_threshold: float = Field(80, gt=0, le=100)
    default_memory_threshold: float = Field(85, gt=0, le=100)
    default_disk_threshold: float = Field(80, gt=0, le=100)

    # Storage
    metric_retention_days: int = Field(30, ge=1)

    # Agent ingestion safety
    max_clock_skew_seconds: int = Field(300, ge=30)
    agent_rate_limit_per_minute: int = Field(30, ge=1)
    admin_auth_failures_per_minute: int = Field(10, ge=1)
    max_request_bytes: int = Field(65536, ge=1024)
    token_ttl_days: int | None = Field(None, ge=1)

    # Optional e-mail notifications
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_username: str | None = None
    smtp_password: str | None = None
    smtp_from: str | None = None
    smtp_to: str = ""
    smtp_starttls: bool = True

    # Web
    frontend_dist: str = "frontend/dist"
    cors_origins: str = ""

    @property
    def smtp_recipients(self) -> list[str]:
        return [addr.strip() for addr in self.smtp_to.split(",") if addr.strip()]

    @property
    def email_enabled(self) -> bool:
        return bool(self.smtp_host and self.smtp_from and self.smtp_recipients)

    @property
    def allowed_origins(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
