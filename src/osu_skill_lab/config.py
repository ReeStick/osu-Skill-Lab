"""Validated configuration, loaded explicitly by entry points."""

from typing import Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="OSU_LAB_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        hide_input_in_errors=True,
    )

    environment: Literal["local", "test", "production"] = "local"
    database_url: SecretStr
    database_timeout_seconds: float = Field(default=3.0, gt=0, le=30)
    osu_client_id: int | None = Field(default=None, gt=0, le=10**12)
    osu_client_secret: SecretStr | None = Field(default=None, repr=False)
    osu_timeout_seconds: float = Field(default=10.0, gt=0, le=30)
    osu_cache_ttl_seconds: int = Field(default=3600, ge=60, le=86400)
    mirror_timeout_seconds: float = Field(default=20.0, gt=0, le=30)
    mirror_cache_ttl_seconds: int = Field(default=600, ge=60, le=86400)
    rabbitmq_url: SecretStr = SecretStr("amqp://osu_lab:osu_lab_local@127.0.0.1:5672/")
    worker_concurrency: int = Field(default=1, ge=1, le=32)

    @field_validator("rabbitmq_url")
    @classmethod
    def validate_rabbitmq_url(cls, value: SecretStr) -> SecretStr:
        from urllib.parse import urlsplit

        try:
            url = urlsplit(value.get_secret_value())
            valid = url.scheme in {"amqp", "amqps"} and url.hostname and url.port != 0
        except ValueError:
            valid = False
        if not valid:
            raise ValueError("RABBITMQ_URL must be an amqp/amqps URL with a host")
        return value

    @field_validator("osu_client_id", "osu_client_secret", mode="before")
    @classmethod
    def empty_credentials(cls, value: object) -> object:
        return None if value == "" else value

    @model_validator(mode="after")
    def validate_osu_credentials(self) -> "Settings":
        if (self.osu_client_id is None) != (self.osu_client_secret is None):
            raise ValueError("OSU_CLIENT_ID and OSU_CLIENT_SECRET must be configured together")
        if self.osu_client_secret is not None:
            secret = self.osu_client_secret.get_secret_value()
            if not secret.strip() or len(secret) > 4096:
                raise ValueError("OSU_CLIENT_SECRET must contain 1 to 4096 characters")
        return self

    @field_validator("database_url")
    @classmethod
    def validate_database_url(cls, value: SecretStr) -> SecretStr:
        try:
            url = make_url(value.get_secret_value())
        except ArgumentError:
            raise ValueError("DATABASE_URL must be a valid SQLAlchemy URL") from None
        if url.drivername != "postgresql+asyncpg" or not url.database or not url.host:
            raise ValueError("DATABASE_URL must use postgresql+asyncpg with a host and database")
        return value
