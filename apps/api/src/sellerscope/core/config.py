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

    # ---- Report exports ----
    report_retention_days: int = Field(default=7, ge=1)
    report_max_rows: int = Field(default=100_000, gt=0)
    # Queued + running exports allowed per organization at once.
    report_max_active: int = Field(default=3, gt=0)

    # ---- Browser extension ----
    extension_token_days: int = Field(default=90, ge=1)
    extension_pairing_ttl_s: int = Field(default=600, ge=60)
    # Attempts to redeem a pairing code, per client IP per minute (brute-force guard).
    extension_pair_ip_per_minute: int = Field(default=10, gt=0)

    # ---- Alert email delivery ----
    alert_delivery_max_attempts: int = Field(default=5, ge=1)
    # Retry n waits base * 2^(n-1) seconds, capped at one hour.
    alert_delivery_backoff_s: float = Field(default=60.0, gt=0)

    # ---- Rate limiting (Redis fixed window) ----
    rate_limit_enabled: bool = True
    rate_limit_ip_per_minute: int = Field(default=300, gt=0)

    # Comma-separated list of allowed browser origins (web app, extension).
    cors_origins: str = "http://localhost:3000"

    # The mock connector produces data labelled MOCK. It is only permitted in development/test.
    enable_mock_connector: bool = False
    # How often MOCK listings drift (sellers rotate, prices move), in seconds. Dev/test only.
    mock_epoch_seconds: int = Field(default=600, gt=0)

    # ---- Observability ----
    # Bearer token Prometheus must send to /metrics (required in staging/production).
    metrics_token: SecretStr | None = None
    sentry_dsn: SecretStr | None = None
    sentry_traces_sample_rate: float = Field(default=0.0, ge=0, le=1)
    # Build identifier (e.g. the git commit), shown in errors and metrics.
    release: str = "dev"

    # Readiness probe timeout for each dependency check, in seconds.
    health_check_timeout_s: float = 2.0

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def is_production_like(self) -> bool:
        return self.app_env in (AppEnv.STAGING, AppEnv.PRODUCTION)

    def _guard_production_settings(self) -> None:
        problems = _problems(self)
        if problems:
            raise ValueError("Unsafe staging/production settings: " + "; ".join(problems))

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
            self._guard_production_settings()
            if self.storage_backend != "s3" or not self.s3_bucket:
                raise ValueError(
                    "STORAGE_BACKEND=s3 and S3_BUCKET are required in staging/production "
                    "(local disk storage is for development only)."
                )
        return self


def _https(url: str) -> bool:
    return url.startswith("https://")


def _problems(settings: Settings) -> list[str]:
    """Production misconfigurations (each one a reason to refuse to start)."""
    problems: list[str] = []
    if not _https(settings.web_base_url):
        problems.append("WEB_BASE_URL must use https://")
    if settings.auth_jwt_issuer and not _https(settings.auth_jwt_issuer):
        problems.append("AUTH_JWT_ISSUER must use https://")
    if settings.auth_jwks_url and not _https(settings.auth_jwks_url):
        problems.append("AUTH_JWKS_URL must use https://")
    bad_origins = [o for o in settings.cors_origin_list if not _https(o) or "*" in o]
    if bad_origins:
        problems.append(f"CORS_ORIGINS must be explicit https:// origins: {bad_origins}")
    secret = settings.auth_jwt_secret.get_secret_value() if settings.auth_jwt_secret else ""
    if secret and len(secret) < 32:
        problems.append("AUTH_JWT_SECRET must be at least 32 characters")
    token = settings.metrics_token.get_secret_value() if settings.metrics_token else ""
    if len(token) < 32:
        problems.append("METRICS_TOKEN (at least 32 characters) is required")
    if not settings.rate_limit_enabled:
        problems.append("RATE_LIMIT_ENABLED must be true")
    if not settings.smtp_starttls:
        problems.append("SMTP_STARTTLS must be true (email credentials must not travel in clear)")
    for name in ("database_url", "redis_url"):
        value = getattr(settings, name).get_secret_value()
        if "change-me" in value:
            problems.append(f"{name.upper()} still uses a placeholder password")
    if settings.log_level.upper() == "DEBUG":
        problems.append("LOG_LEVEL=DEBUG is not allowed (it can log sensitive data)")
    return problems


@lru_cache
def get_settings() -> Settings:
    return Settings()
