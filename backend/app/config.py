from functools import lru_cache
from typing import Literal

from pydantic import SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import URL

LOCAL_ONLY_SECRETS = {
    "local_auth_only",
    "local_limited_only",
    "local_exec_only",
    "local-development-session-secret-change-me",
}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="PHARMA_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    environment: Literal["local", "demo", "staging", "prod"] = "local"
    api_prefix: str = "/api/v1"

    db_host: str = "localhost"
    db_port: int = 5433
    db_name: str = "pharma"
    db_auth_user: str = "pharma_runtime_auth"
    db_auth_password: SecretStr = SecretStr("local_auth_only")
    db_limited_user: str = "pharma_runtime_limited"
    db_limited_password: SecretStr = SecretStr("local_limited_only")
    db_exec_user: str = "pharma_runtime_exec"
    db_exec_password: SecretStr = SecretStr("local_exec_only")

    session_secret: SecretStr = SecretStr("local-development-session-secret-change-me")
    session_cookie_name: str = "pharma_session"
    session_max_age_seconds: int = 8 * 60 * 60
    cookie_secure: bool = False

    query_timeout_ms: int = 5_000
    db_pool_size: int = 5
    db_max_overflow: int = 5

    @model_validator(mode="after")
    def reject_local_secrets_outside_local(self) -> "Settings":
        secrets = {
            self.db_auth_password.get_secret_value(),
            self.db_limited_password.get_secret_value(),
            self.db_exec_password.get_secret_value(),
            self.session_secret.get_secret_value(),
        }
        if self.environment != "local" and secrets & LOCAL_ONLY_SECRETS:
            raise ValueError("Local-only database or session secrets cannot be used outside local")
        if len(self.session_secret.get_secret_value()) < 32:
            raise ValueError("session_secret must be at least 32 characters")
        return self

    def database_url(self, *, username: str, password: SecretStr) -> URL:
        return URL.create(
            drivername="postgresql+psycopg",
            username=username,
            password=password.get_secret_value(),
            host=self.db_host,
            port=self.db_port,
            database=self.db_name,
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
