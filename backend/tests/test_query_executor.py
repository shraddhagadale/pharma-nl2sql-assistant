import pytest

from app.agent.models import AnalyticsPlan, QueryParameter
from app.db.pools import DatabasePools
from app.models import UserContext, UserRole
from app.sql.executor import QueryExecutor, UnknownProductError
from app.sql.validator import SqlValidator


@pytest.mark.asyncio
async def test_unknown_product_is_not_reported_as_zero(settings) -> None:
    executor = QueryExecutor(DatabasePools(settings))
    query = SqlValidator(max_rows=100).validate(
        AnalyticsPlan(
            metric_id="paid_demand",
            time_window_id="last_month",
            sql="""
                SELECT :product_name AS product,
                       COALESCE(SUM(s.pack_units), 0) AS paid_demand
                FROM sales AS s
                WHERE s.data_source = 'distributor'
                  AND s.brand_flag = 1
                  AND s.mo_offset = 1
                  AND UPPER(s.drug_name) = UPPER(:product_name)
            """,
            parameters=[QueryParameter(name="product_name", value="MoonCure")],
        ),
        role=UserRole.RAM,
    )
    user = UserContext(
        user_id="U009",
        email="amy.nguyen@novapharma.com",
        full_name="Amy Nguyen",
        role=UserRole.RAM,
        territory_name="New York Metro",
        region_name="Northeast",
        can_view_wac=False,
    )

    try:
        with pytest.raises(UnknownProductError, match="MoonCure"):
            await executor.execute(query, user=user)
    finally:
        await executor.pools.dispose()
