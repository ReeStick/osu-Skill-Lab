from pathlib import Path

import pytest
from pydantic import SecretStr, ValidationError

from osu_skill_lab.config import Settings

DATABASE_URL = "postgresql+asyncpg://user:private-password@localhost/osu_skill_lab"


def test_database_url_is_required() -> None:
    with pytest.raises(ValidationError, match="database_url"):
        Settings(_env_file=None)


def test_environment_overrides_dotenv(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    dotenv = tmp_path / ".env"
    dotenv.write_text(
        f"OSU_LAB_DATABASE_URL={DATABASE_URL}\nOSU_LAB_ENVIRONMENT=local\nPOSTGRES_PORT=5432\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("OSU_LAB_ENVIRONMENT", "test")
    settings = Settings(_env_file=dotenv)
    assert settings.environment == "test"
    assert settings.database_url.get_secret_value() == DATABASE_URL
    assert "private-password" not in repr(settings)
    assert "private-password" not in settings.model_dump_json()


@pytest.mark.parametrize("value", ["not-a-url", "sqlite:///local.db", "postgresql://host/db"])
def test_rejects_unsupported_database_urls(value: str) -> None:
    with pytest.raises(ValidationError, match="DATABASE_URL"):
        Settings(_env_file=None, database_url=SecretStr(value))


@pytest.mark.parametrize("value", [0, -1, 31, float("inf"), float("nan")])
def test_rejects_unbounded_database_timeouts(value: float) -> None:
    with pytest.raises(ValidationError):
        Settings(
            _env_file=None, database_url=SecretStr(DATABASE_URL), database_timeout_seconds=value
        )


def test_validation_error_hides_input_values() -> None:
    with pytest.raises(ValidationError) as error:
        Settings(_env_file=None, database_url=SecretStr("private-password"))
    assert "private-password" not in str(error.value)


def test_url_encoded_password_is_preserved() -> None:
    url = "postgresql+asyncpg://user:p%25ss%40word@localhost/osu_skill_lab"
    assert (
        Settings(_env_file=None, database_url=SecretStr(url)).database_url.get_secret_value() == url
    )


def test_osu_credentials_are_optional_and_blank_compose_values_disable_them(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OSU_LAB_OSU_CLIENT_ID", "")
    monkeypatch.setenv("OSU_LAB_OSU_CLIENT_SECRET", "")
    settings = Settings(_env_file=None, database_url=SecretStr(DATABASE_URL))
    assert settings.osu_client_id is None
    assert settings.osu_client_secret is None


@pytest.mark.parametrize("missing", ["id", "secret"])
def test_osu_credentials_must_be_configured_together(missing: str) -> None:
    with pytest.raises(ValidationError, match="configured together") as error:
        Settings(
            _env_file=None,
            database_url=SecretStr(DATABASE_URL),
            osu_client_id=None if missing == "id" else 123,
            osu_client_secret=None if missing == "secret" else SecretStr("private-osu-secret"),
        )
    assert "private-osu-secret" not in str(error.value)


def test_osu_secret_is_hidden_from_representation_and_serialization() -> None:
    settings = Settings(
        _env_file=None,
        database_url=SecretStr(DATABASE_URL),
        osu_client_id=123,
        osu_client_secret=SecretStr("private-osu-secret"),
    )
    assert "private-osu-secret" not in repr(settings) + settings.model_dump_json()


@pytest.mark.parametrize("secret", [" ", "x" * 4097], ids=["blank", "too_long"])
def test_osu_secret_has_bounded_nonblank_content(secret: str) -> None:
    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,
            database_url=SecretStr(DATABASE_URL),
            osu_client_id=123,
            osu_client_secret=SecretStr(secret),
        )


@pytest.mark.parametrize("ttl", [0, 59, 86401])
def test_osu_cache_ttl_is_bounded_and_at_least_one_minute(ttl: int) -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, database_url=SecretStr(DATABASE_URL), osu_cache_ttl_seconds=ttl)
