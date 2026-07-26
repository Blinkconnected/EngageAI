"""Application configuration.

All runtime configuration is sourced from environment variables (see
``.env.example`` at the repository root). No secrets are hard-coded.
"""

from functools import lru_cache
from typing import Annotated, Literal

from pydantic import Field, PostgresDsn, RedisDsn, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- Application ---
    app_name: str = "Blink Engage"
    environment: Literal["development", "test", "staging", "production"] = "development"
    debug: bool = False
    api_v1_prefix: str = "/api/v1"
    # The externally-visible scheme+host this API is served at (no
    # trailing slash) — used to reconstruct the *exact* webhook URL for
    # providers whose signature scheme signs the full URL (e.g. Twilio
    # SMS, see docs/architecture/sms.md). Deliberately a fixed setting
    # rather than trusting X-Forwarded-Proto/Host from the request: this
    # app's backend port is reachable directly (not only via nginx), so
    # trusting client-supplied forwarded headers for signature-relevant
    # URL reconstruction would be spoofable.
    public_base_url: str = "http://localhost"

    # --- Security ---
    jwt_secret_key: str = Field(..., min_length=32)
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 15
    refresh_token_expire_days: int = 30
    # How long a CSAT survey link stays valid after a conversation closes
    # (see docs/architecture/reports-analytics.md) — long enough for a
    # customer to get to it, unlike the much shorter access/refresh token
    # lifetimes above, since this token is emailed/messaged to a customer
    # rather than kept alive by an active session.
    csat_token_expire_days: int = 14
    # Encrypts secrets-at-rest (e.g. channel provider credentials — see
    # docs/architecture/channels.md). Deliberately separate from
    # jwt_secret_key so rotating one never invalidates the other.
    credentials_encryption_key: str = Field(..., min_length=32)

    # --- CORS ---
    # NoDecode: pydantic-settings otherwise tries to JSON-decode list-typed env
    # vars before our validator runs, which rejects a plain comma-separated string.
    cors_allow_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["http://localhost:5173"]
    )

    # --- Database ---
    database_url: str = Field(..., description="Async SQLAlchemy DSN")
    database_pool_size: int = 10
    database_max_overflow: int = 20
    database_echo: bool = False

    # --- Redis ---
    redis_url: str = "redis://localhost:6379/0"

    # --- RabbitMQ / Celery ---
    rabbitmq_url: str = "amqp://guest:guest@localhost:5672/"
    celery_result_backend: str = "redis://localhost:6379/1"

    # --- Domain event bus (see docs/architecture/event-bus.md) ---
    events_exchange_name: str = "blinkengage.events"
    events_relay_batch_size: int = 100
    # Dead-letter guard: a row that fails this many times is excluded from
    # future claim_batch() calls (but not deleted) so one poisoned event
    # can't starve the relay's FIFO batch of every healthy event behind it
    # — see EventOutboxRepository.claim_batch's docstring for the real
    # incident this guards against.
    events_relay_max_attempts: int = 10

    # --- Object storage (MinIO / S3-compatible) ---
    s3_endpoint_url: str = "http://localhost:9000"
    s3_access_key: str = "minioadmin"
    s3_secret_key: str = "minioadmin"
    s3_bucket_attachments: str = "blinkengage-attachments"
    s3_use_ssl: bool = False

    # --- Attachments (see docs/architecture/conversations.md) ---
    attachment_max_size_bytes: int = 25 * 1024 * 1024  # 25 MiB
    attachment_allowed_content_types: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: [
            "image/png",
            "image/jpeg",
            "image/gif",
            "image/webp",
            "application/pdf",
            "text/plain",
            "text/csv",
            "application/msword",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "application/vnd.ms-excel",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ]
    )

    # --- AI Engine (see docs/architecture/ai-engine.md) ---
    # Platform-level, not per-company: matches how these settings were
    # already structured before this milestone (env-configured, not a
    # ChannelConfig-style per-company credential row) — simpler, and a
    # per-company "bring your own AI provider" model can be layered on
    # later without a breaking change if a real enterprise need for it
    # emerges.
    ai_provider: Literal["openai", "claude", "ollama", "disabled"] = "disabled"
    ai_model: str | None = None
    ai_default_max_tokens: int = 1000
    openai_api_key: str | None = None
    openai_base_url: str = "https://api.openai.com/v1"
    anthropic_api_key: str | None = None
    anthropic_base_url: str = "https://api.anthropic.com/v1"
    ollama_base_url: str = "http://localhost:11434"

    # --- Rate limiting ---
    rate_limit_per_minute: int = 60
    # Tighter than the generic limit above, and per-*user* rather than
    # per-IP (see api/deps.py::enforce_ai_rate_limit) — every AI Engine
    # call has a real external cost, unlike auth/webchat, which only cost
    # a DB round trip.
    ai_rate_limit_per_minute: int = 20
    # Per-user, like the AI limit above — "Test Connection" makes the
    # server originate a real outbound connection to an operator-chosen
    # host/port on every call (see channel-integration-spec.md's security
    # review), so it gets the same treatment as any other real-network-
    # cost action, not the generic per-IP limit.
    channel_test_connection_rate_limit_per_minute: int = 20
    # Same reasoning, applied to ERP "Test Connection" (see
    # docs/architecture/company-onboarding.md).
    erp_test_connection_rate_limit_per_minute: int = 20

    # --- Web Chat (see docs/architecture/web-chat.md) ---
    webchat_session_ttl_hours: int = 720  # 30 days, sliding

    # --- Platform/system email (see docs/architecture/notifications.md) ---
    # Distinct from a company's per-channel EmailProvider credentials
    # (M15, ChannelConfig.credentials) — this is the platform's own
    # outbound email for transactional/system notifications (e.g. "you
    # were assigned a conversation"), which must work even for a company
    # that hasn't configured any customer-facing email channel.
    smtp_host: str = "localhost"
    smtp_port: int = 587
    smtp_username: str | None = None
    smtp_password: str | None = None
    smtp_use_tls: bool = True
    smtp_from_address: str = "notifications@blinkengage.local"
    smtp_from_name: str = "Blink Engage"

    @field_validator("cors_allow_origins", "attachment_allowed_content_types", mode="before")
    @classmethod
    def _split_origins(cls, value: str | list[str]) -> list[str]:
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value

    @property
    def is_production(self) -> bool:
        return self.environment == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()


# Re-exported for typing convenience where a concrete DSN type is useful.
__all__ = ["Settings", "get_settings", "PostgresDsn", "RedisDsn"]
