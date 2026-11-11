"""Application settings loaded from environment variables (see .env.example)."""

from __future__ import annotations

from enum import StrEnum
from functools import lru_cache

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class AppEnv(StrEnum):
    DEVELOPMENT = "development"
    TEST = "test"
    STAGING = "staging"
    PRODUCTION = "production"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: AppEnv = AppEnv.DEVELOPMENT
    app_name: str = "SellerScope API"
    log_level: str = "INFO"

    database_url: SecretStr = Field(
        default=SecretStr("postgresql+asyncpg://sellerscope:sellerscope@localhost:5432/sellerscope")
    )
    # Schema owner used only by migrations. The API itself connects as the restricted app
    # role via DATABASE_URL, which has no DDL rights and is subject to row-level security.
    migration_database_url: SecretStr | None = None
    # Name of the restricted role that migrations grant privileges to.
    app_db_role: str = "sellerscope_app"

    redis_url: SecretStr = Field(default=SecretStr("redis://localhost:6379/0"))

    # Comma-separated list of allowed browser origins (web app, extension).
    cors_origins: str = "http://localhost:3000"

    # The mock connector produces data labelled MOCK. It is only permitted in development/test.
    enable_mock_connector: bool = False

    # Readiness probe timeout for each dependency check, in seconds.
    health_check_timeout_s: float = 2.0

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def is_production_like(self) -> bool:
        return self.app_env in (AppEnv.STAGING, AppEnv.PRODUCTION)

    @model_validator(mode="after")
    def _guard_production(self) -> Settings:
        if self.is_production_like and self.enable_mock_connector:
            raise ValueError(
                "ENABLE_MOCK_CONNECTOR must be false in staging/production: "
                "mock data must never reach real customers."
            )
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
