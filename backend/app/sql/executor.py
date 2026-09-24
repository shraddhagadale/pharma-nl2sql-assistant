from datetime import date, datetime
from decimal import Decimal

from app.agent.models import QueryResult
from app.db.pools import DatabasePools
from app.models import JsonScalar, UserContext
from app.sql.validator import ValidatedQuery


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
            result = await connection.exec_driver_sql(query.sql, query.parameters)
            columns = list(result.keys())
            rows = [
                {column: self._json_value(value) for column, value in dict(row).items()}
                for row in result.mappings().all()
            ]
        return QueryResult(columns=columns, rows=rows)

    @staticmethod
    def _json_value(value: object) -> JsonScalar:
        if value is None or isinstance(value, (str, int, float, bool)):
            return value
        if isinstance(value, Decimal):
            return str(value)
        if isinstance(value, (date, datetime)):
            return value.isoformat()
        return str(value)
