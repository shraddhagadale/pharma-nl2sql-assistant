from sqlalchemy import text

from app.db.pools import DatabaseAccess, DatabasePools
from app.models import UserContext

USER_COLUMNS = """
    user_id,
    email,
    full_name,
    role,
    territory_name,
    region_name,
    can_view_wac
"""


class UserRepository:
    def __init__(self, pools: DatabasePools) -> None:
        self.pools = pools

    async def list_users(self) -> list[UserContext]:
        query = text(
            f"""
            SELECT {USER_COLUMNS}
            FROM users
            ORDER BY
                CASE role WHEN 'exec' THEN 1 WHEN 'director' THEN 2 ELSE 3 END,
                full_name
            """
        )
        async with self.pools.transaction(DatabaseAccess.AUTH) as connection:
            rows = (await connection.execute(query)).mappings().all()
        return [self._to_user(row) for row in rows]

    async def get_user(self, user_id: str) -> UserContext | None:
        query = text(
            f"""
            SELECT {USER_COLUMNS}
            FROM users
            WHERE user_id = :user_id
            """
        )
        async with self.pools.transaction(DatabaseAccess.AUTH) as connection:
            row = (await connection.execute(query, {"user_id": user_id})).mappings().one_or_none()
        return None if row is None else self._to_user(row)

    @staticmethod
    def _to_user(row: object) -> UserContext:
        return UserContext.model_validate(
            {
                **dict(row),
                "can_view_wac": bool(row["can_view_wac"]),
            }
        )
