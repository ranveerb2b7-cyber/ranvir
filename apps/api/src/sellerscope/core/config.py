"""Application settings loaded from environment variables (see .env.example)."""

from __future__ import annotations

from enum import StrEnum
from functools import lru_cache
from typing import Literal

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

    # ---- Authentication (Supabase Auth / GoTrue access tokens) ----
    # Expected `iss` claim, e.g. https://<project>.supabase.co/auth/v1 (hosted) or the local
    # GoTrue URL. Tokens are verified with JWKS (RS256/ES256) and/or a shared HS256 secret.
    auth_jwt_issuer: str | None = None
    auth_jwt_audience: str = "authenticated"
    auth_jwks_url: str | None = None
    auth_jwt_secret: SecretStr | None = None

    # ---- Web app / email ----
    web_base_url: str = "http://localhost:3000"
    smtp_host: str = "localhost"
    smtp_port: int = 1025
    smtp_username: str | None = None
    smtp_password: SecretStr | None = None
    smtp_starttls: bool = False
    smtp_from: str = "SellerScope <no-reply@sellerscope.local>"
    invitation_ttl_hours: int = Field(default=168, gt=0)

    # ---- File storage (uploads, later exports) ----
    # "local" stores files on disk (development/tests only); "s3" uses S3-compatible storage.
    storage_backend: Literal["local", "s3"] = "local"
    storage_local_dir: str = ".storage"
    s3_bucket: str | None = None
    s3_endpoint_url: str | None = None  # e.g. MinIO / Cloudflare R2; None = AWS
    s3_region: str = "ap-south-1"
    s3_access_key_id: str | None = None
    s3_secret_access_key: SecretStr | None = None

    # ---- Product uploads ----
    upload_max_bytes: int = Field(default=10 * 1024 * 1024, gt=0)
    upload_max_rows: int = Field(default=50_000, gt=0)

    # ---- Scanning engine ----
    scan_max_attempts: int = Field(default=6, ge=1)
    scan_backoff_base_s: float = Field(default=2.0, gt=0)
    scan_backoff_cap_s: float = Field(default=300.0, gt=0)
    # Rate-limit waits up to this long are slept in the worker; longer ones reschedule the job.
    scan_inline_wait_max_s: float = Field(default=10.0, ge=0)
    # A worker processes a job for at most this long, then re-queues it (fairness).
    scan_run_budget_s: float = Field(default=240.0, gt=0)
    # Items stuck in "processing" longer than this are returned to the queue.
    scan_stale_after_s: int = Field(default=600, gt=0)
    scan_schedule_batch: int = Field(default=500, gt=0)

    # ---- Rate limiting (Redis fixed window) ----
    rate_limit_enabled: bool = True
    rate_limit_ip_per_minute: int = Field(default=300, gt=0)

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
        if self.is_production_like:
            if not self.auth_jwt_issuer:
                raise ValueError("AUTH_JWT_ISSUER is required in staging/production.")
            if not (self.auth_jwks_url or self.auth_jwt_secret):
                raise ValueError(
                    "AUTH_JWKS_URL or AUTH_JWT_SECRET is required in staging/production."
                )
            if self.storage_backend != "s3" or not self.s3_bucket:
                raise ValueError(
                    "STORAGE_BACKEND=s3 and S3_BUCKET are required in staging/production "
                    "(local disk storage is for development only)."
                )
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
