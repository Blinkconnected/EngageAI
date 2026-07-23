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

    # --- Security ---
    jwt_secret_key: str = Field(..., min_length=32)
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 15
    refresh_token_expire_days: int = 30

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

    # --- Object storage (MinIO / S3-compatible) ---
    s3_endpoint_url: str = "http://localhost:9000"
    s3_access_key: str = "minioadmin"
    s3_secret_key: str = "minioadmin"
    s3_bucket_attachments: str = "blinkengage-attachments"
    s3_use_ssl: bool = False

    # --- AI providers ---
    openai_api_key: str | None = None
    anthropic_api_key: str | None = None
    ollama_base_url: str = "http://localhost:11434"

    # --- Rate limiting ---
    rate_limit_per_minute: int = 60

    @field_validator("cors_allow_origins", mode="before")
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
