import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.config import Settings
from app.main import create_app


@pytest.fixture(scope="session")
def settings() -> Settings:
    return Settings(
        environment="local",
        db_host="localhost",
        db_port=5433,
        db_name="pharma",
        db_auth_user="pharma_runtime_auth",
        db_auth_password=SecretStr("local_auth_only"),
        db_limited_user="pharma_runtime_limited",
        db_limited_password=SecretStr("local_limited_only"),
        db_exec_user="pharma_runtime_exec",
        db_exec_password=SecretStr("local_exec_only"),
        session_secret=SecretStr("test-session-secret-with-at-least-32-characters"),
        cookie_secure=False,
    )


@pytest.fixture
def client(settings: Settings):
    with TestClient(create_app(settings)) as test_client:
        yield test_client
