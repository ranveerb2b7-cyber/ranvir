import pytest
from pydantic import ValidationError

from sellerscope.core.config import AppEnv, Settings


@pytest.mark.parametrize("env", [AppEnv.STAGING, AppEnv.PRODUCTION])
def test_mock_connector_rejected_in_production_like_envs(env: AppEnv) -> None:
    with pytest.raises(ValidationError, match="ENABLE_MOCK_CONNECTOR"):
        Settings(app_env=env, enable_mock_connector=True)


@pytest.mark.parametrize("env", [AppEnv.DEVELOPMENT, AppEnv.TEST])
def test_mock_connector_allowed_in_dev_and_test(env: AppEnv) -> None:
    assert Settings(app_env=env, enable_mock_connector=True).enable_mock_connector


def test_secrets_are_not_exposed_in_repr() -> None:
    s = Settings(database_url="postgresql+asyncpg://u:supersecret@h/db")  # type: ignore[arg-type]
    assert "supersecret" not in repr(s)


def test_cors_origin_list_parsing() -> None:
    s = Settings(cors_origins=" http://a.test , ,chrome-extension://abc ")
    assert s.cors_origin_list == ["http://a.test", "chrome-extension://abc"]
