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


@pytest.mark.asyncio
async def test_weekly_sales_covering_index_is_ready(settings):
    pools = DatabasePools(settings)
    try:
        async with pools.transaction(DatabaseAccess.LIMITED, user_id="U009") as connection:
            result = await connection.execute(
                text(
                    """
                        SELECT index_metadata.indisready,
                               index_metadata.indisvalid,
                               pg_get_indexdef(index_relation.oid) AS definition
                        FROM pg_class AS index_relation
                        JOIN pg_index AS index_metadata
                          ON index_metadata.indexrelid = index_relation.oid
                        WHERE index_relation.relname =
                              'sales_week_source_brand_org_cover_idx'
                          AND index_relation.relnamespace = 'public'::regnamespace
                    """
                )
            )
            index_state = result.mappings().one()

            assert index_state["indisready"] is True
            assert index_state["indisvalid"] is True
            assert "(data_source, wk_offset, brand_flag, org_id)" in index_state["definition"]
            assert "INCLUDE (pack_units, total_mg, ndc)" in index_state["definition"]
    finally:
        await pools.dispose()
