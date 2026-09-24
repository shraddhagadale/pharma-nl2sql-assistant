from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from enum import StrEnum

from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine

from app.config import Settings
from app.models import UserContext, UserRole


class DatabaseAccess(StrEnum):
    AUTH = "auth"
    LIMITED = "limited"
    EXEC = "exec"


DATABASE_ROLES = {
    DatabaseAccess.AUTH: "pharma_app_auth",
    DatabaseAccess.LIMITED: "pharma_app_limited",
    DatabaseAccess.EXEC: "pharma_app_exec",
}


class DatabasePools:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._engines = {
            DatabaseAccess.AUTH: self._create_engine(
                username=settings.db_auth_user,
                password=settings.db_auth_password,
            ),
            DatabaseAccess.LIMITED: self._create_engine(
                username=settings.db_limited_user,
                password=settings.db_limited_password,
            ),
            DatabaseAccess.EXEC: self._create_engine(
                username=settings.db_exec_user,
                password=settings.db_exec_password,
            ),
        }

    def _create_engine(self, *, username: str, password: SecretStr) -> AsyncEngine:
        return create_async_engine(
            self.settings.database_url(username=username, password=password),
            pool_pre_ping=True,
            pool_size=self.settings.db_pool_size,
            max_overflow=self.settings.db_max_overflow,
            pool_recycle=1_800,
            hide_parameters=True,
        )

    @staticmethod
    def access_for_user(user: UserContext) -> DatabaseAccess:
        if user.role is UserRole.EXEC:
            return DatabaseAccess.EXEC
        return DatabaseAccess.LIMITED

    @asynccontextmanager
    async def transaction(
        self,
        access: DatabaseAccess,
        *,
        user_id: str | None = None,
    ) -> AsyncIterator[AsyncConnection]:
        engine = self._engines[access]
        database_role = DATABASE_ROLES[access]

        async with engine.connect() as connection:
            async with connection.begin():
                await connection.exec_driver_sql("SET TRANSACTION READ ONLY")
                await connection.exec_driver_sql(f"SET LOCAL ROLE {database_role}")
                await connection.execute(
                    text("SELECT set_config('statement_timeout', :timeout, true)"),
                    {"timeout": str(self.settings.query_timeout_ms)},
                )
                if user_id is not None:
                    await connection.execute(
                        text("SELECT set_config('app.user_id', :user_id, true)"),
                        {"user_id": user_id},
                    )
                yield connection

    async def check(self) -> None:
        for access in DatabaseAccess:
            async with self.transaction(access) as connection:
                await connection.execute(text("SELECT 1"))

    async def dispose(self) -> None:
        for engine in self._engines.values():
            await engine.dispose()
