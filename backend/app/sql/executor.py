from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import text

from app.agent.models import QueryResult
from app.db.pools import DatabasePools
from app.models import JsonScalar, UserContext
from app.sql.validator import ValidatedQuery


class UnknownProductError(ValueError):
    def __init__(self, product_name: str) -> None:
        self.product_name = product_name
        super().__init__(f"Unknown product: {product_name}")


class QueryExecutor:
    def __init__(self, pools: DatabasePools) -> None:
        self.pools = pools

    async def execute(
        self,
        query: ValidatedQuery,
        *,
        user: UserContext,
    ) -> QueryResult:
        access = self.pools.access_for_user(user)
        async with self.pools.transaction(access, user_id=user.user_id) as connection:
            await self._ensure_known_products(connection, query)
            result = await connection.exec_driver_sql(query.sql, query.parameters)
            columns = list(result.keys())
            rows = [
                {column: self._json_value(value) for column, value in dict(row).items()}
                for row in result.mappings().all()
            ]
        return QueryResult(columns=columns, rows=rows)

    @staticmethod
    async def _ensure_known_products(connection, query: ValidatedQuery) -> None:
        for column_name, parameter_name in query.product_lookups:
            value = query.parameters.get(parameter_name)
            if not isinstance(value, str):
                continue
            exists = await connection.scalar(
                text(
                    f"SELECT 1 FROM products "
                    f"WHERE UPPER({column_name}) = UPPER(:product_value) LIMIT 1"
                ),
                {"product_value": value},
            )
            if exists is None:
                raise UnknownProductError(value)

    @staticmethod
    def _json_value(value: object) -> JsonScalar:
        if value is None or isinstance(value, (str, int, float, bool)):
            return value
        if isinstance(value, Decimal):
            return str(value)
        if isinstance(value, (date, datetime)):
            return value.isoformat()
        return str(value)
