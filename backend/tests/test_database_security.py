import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.db.pools import DatabaseAccess, DatabasePools


@pytest.mark.asyncio
async def test_runtime_identities_cannot_cross_privilege_boundaries(settings):
    pools = DatabasePools(settings)
    try:
        with pytest.raises(DBAPIError):
            async with pools.transaction(DatabaseAccess.AUTH) as connection:
                await connection.execute(text("SELECT count(*) FROM sales"))

        with pytest.raises(DBAPIError):
            async with pools.transaction(DatabaseAccess.LIMITED) as connection:
                await connection.exec_driver_sql("SET LOCAL ROLE pharma_app_exec")
    finally:
        await pools.dispose()


@pytest.mark.asyncio
async def test_transaction_local_user_context_does_not_leak(settings):
    pools = DatabasePools(settings)
    try:
        async with pools.transaction(DatabaseAccess.LIMITED, user_id="U009") as connection:
            active_user = await connection.scalar(
                text("SELECT current_setting('app.user_id', true)")
            )
            assert active_user == "U009"

        async with pools.transaction(DatabaseAccess.LIMITED) as connection:
            next_user = await connection.scalar(text("SELECT current_setting('app.user_id', true)"))
            assert next_user != "U009"
    finally:
        await pools.dispose()
