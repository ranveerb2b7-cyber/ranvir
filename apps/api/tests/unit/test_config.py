import pytest
from pydantic import ValidationError

from sellerscope.core.config import AppEnv, Settings

PROD_AUTH = {
    "auth_jwt_issuer": "https://auth.example/auth/v1",
    "auth_jwks_url": "https://auth.example/auth/v1/.well-known/jwks.json",
    "storage_backend": "s3",
    "s3_bucket": "sellerscope-prod",
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
