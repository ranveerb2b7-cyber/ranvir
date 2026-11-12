import pytest
from pydantic import ValidationError

from sellerscope.core.config import AppEnv, Settings

PROD_AUTH = {
    "auth_jwt_issuer": "https://auth.example/auth/v1",
    "auth_jwks_url": "https://auth.example/auth/v1/.well-known/jwks.json",
    "storage_backend": "s3",
    "s3_bucket": "sellerscope-prod",
    # A complete, safe production configuration (placeholders, not real secrets).
    "web_base_url": "https://app.sellerscope.example",
    "cors_origins": "https://app.sellerscope.example",
    "metrics_token": "m" * 40,
    "smtp_starttls": True,
    "database_url": "postgresql+asyncpg://app:prod-secret@db.internal:5432/sellerscope",
    "redis_url": "rediss://:prod-secret@cache.internal:6379/0",
}


@pytest.mark.parametrize("env", [AppEnv.STAGING, AppEnv.PRODUCTION])
def test_mock_connector_rejected_in_production_like_envs(env: AppEnv) -> None:
    with pytest.raises(ValidationError, match="ENABLE_MOCK_CONNECTOR"):
        Settings(app_env=env, enable_mock_connector=True, **PROD_AUTH)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"auth_jwt_issuer": None}, "AUTH_JWT_ISSUER"),
        ({"auth_jwks_url": None}, "AUTH_JWKS_URL or AUTH_JWT_SECRET"),
    ],
)
def test_production_requires_auth_configuration(overrides: dict[str, None], message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        Settings(app_env=AppEnv.PRODUCTION, **{**PROD_AUTH, **overrides})  # type: ignore[arg-type]


@pytest.mark.parametrize("env", [AppEnv.DEVELOPMENT, AppEnv.TEST])
def test_mock_connector_allowed_in_dev_and_test(env: AppEnv) -> None:
    assert Settings(app_env=env, enable_mock_connector=True).enable_mock_connector


def test_secrets_are_not_exposed_in_repr() -> None:
    s = Settings(database_url="postgresql+asyncpg://u:supersecret@h/db")  # type: ignore[arg-type]
    assert "supersecret" not in repr(s)


def test_cors_origin_list_parsing() -> None:
    s = Settings(cors_origins=" http://a.test , ,chrome-extension://abc ")
    assert s.cors_origin_list == ["http://a.test", "chrome-extension://abc"]


def test_production_requires_s3_storage() -> None:
    with pytest.raises(ValidationError, match="STORAGE_BACKEND=s3"):
        Settings(app_env=AppEnv.PRODUCTION, **{**PROD_AUTH, "storage_backend": "local"})  # type: ignore[arg-type]


def test_a_complete_production_configuration_is_accepted() -> None:
    settings = Settings(app_env=AppEnv.PRODUCTION, **PROD_AUTH)  # type: ignore[arg-type]
    assert settings.is_production_like


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"web_base_url": "http://app.sellerscope.example"}, "WEB_BASE_URL must use https"),
        ({"cors_origins": "https://ok.example,http://bad.example"}, "CORS_ORIGINS"),
        ({"cors_origins": "*"}, "CORS_ORIGINS"),
        ({"metrics_token": None}, "METRICS_TOKEN"),
        ({"metrics_token": "short"}, "METRICS_TOKEN"),
        ({"rate_limit_enabled": False}, "RATE_LIMIT_ENABLED"),
        ({"smtp_starttls": False}, "SMTP_STARTTLS"),
        ({"database_url": "postgresql+asyncpg://a:change-me-app@db/x"}, "DATABASE_URL"),
        ({"log_level": "DEBUG"}, "LOG_LEVEL=DEBUG"),
        ({"auth_jwks_url": None, "auth_jwt_secret": "too-short"}, "AUTH_JWT_SECRET"),
        ({"auth_jwt_issuer": "http://auth.example/auth/v1"}, "AUTH_JWT_ISSUER must use https"),
    ],
)
@pytest.mark.parametrize("env", [AppEnv.STAGING, AppEnv.PRODUCTION])
def test_unsafe_production_settings_are_refused(
    env: AppEnv, overrides: dict[str, object], message: str
) -> None:
    with pytest.raises(ValidationError, match=message):
        Settings(app_env=env, **{**PROD_AUTH, **overrides})  # type: ignore[arg-type]


def test_development_keeps_local_defaults() -> None:
    settings = Settings(app_env=AppEnv.DEVELOPMENT, web_base_url="http://localhost:3000")
    assert settings.metrics_token is None and settings.sentry_dsn is None
