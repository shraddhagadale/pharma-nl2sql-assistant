import re

from sqlalchemy import text

from app.agent.models import GeographyKind, GeographyReference
from app.db.pools import DatabasePools
from app.models import UserContext, UserRole

STATE_CODES = {
    "alabama": "AL",
    "arizona": "AZ",
    "arkansas": "AR",
    "california": "CA",
    "colorado": "CO",
    "connecticut": "CT",
    "delaware": "DE",
    "district of columbia": "DC",
    "florida": "FL",
    "georgia": "GA",
    "illinois": "IL",
    "indiana": "IN",
    "iowa": "IA",
    "louisiana": "LA",
    "maryland": "MD",
    "massachusetts": "MA",
    "michigan": "MI",
    "minnesota": "MN",
    "mississippi": "MS",
    "nevada": "NV",
    "new hampshire": "NH",
    "new jersey": "NJ",
    "new mexico": "NM",
    "new york": "NY",
    "north carolina": "NC",
    "north dakota": "ND",
    "ohio": "OH",
    "oklahoma": "OK",
    "oregon": "OR",
    "pennsylvania": "PA",
    "rhode island": "RI",
    "south carolina": "SC",
    "texas": "TX",
    "utah": "UT",
    "virginia": "VA",
    "washington": "WA",
    "washington dc": "DC",
    "west virginia": "WV",
    "wisconsin": "WI",
}


class GeographyScopeRepository:
    def __init__(self, pools: DatabasePools) -> None:
        self.pools = pools

    async def is_within_scope(
        self,
        reference: GeographyReference,
        *,
        user: UserContext,
    ) -> bool | None:
        if user.role is UserRole.EXEC:
            return True

        predicate = self._predicate(reference)
        if predicate is None:
            return None
        sql, parameters = predicate

        access = self.pools.access_for_user(user)
        async with self.pools.transaction(access, user_id=user.user_id) as connection:
            result = await connection.execute(text(sql), parameters)
            rows = result.mappings().all()

        if not rows:
            return None
        if user.role is UserRole.RAM:
            return any(_same_name(row["territory_name"], user.territory_name) for row in rows)
        return any(_same_name(row["region_name"], user.region_name) for row in rows)

    @staticmethod
    def _predicate(reference: GeographyReference) -> tuple[str, dict[str, str]] | None:
        if reference.kind is GeographyKind.CITY:
            if not reference.state:
                return None
            state = _state_code(reference.state)
            return _state_predicate(state) if state else None
        if reference.kind is GeographyKind.STATE:
            state = _state_code(reference.name)
            return _state_predicate(state) if state else None
        if reference.kind is GeographyKind.TERRITORY:
            return (
                """
                SELECT DISTINCT territory_name, region_name
                FROM zip_territory
                WHERE LOWER(territory_name) = LOWER(:name)
                """,
                {"name": reference.name},
            )
        if reference.kind is GeographyKind.REGION:
            return (
                """
                SELECT DISTINCT territory_name, region_name
                FROM zip_territory
                WHERE LOWER(region_name) = LOWER(:name)
                """,
                {"name": reference.name},
            )
        if reference.kind is GeographyKind.ZIP:
            return (
                """
                SELECT DISTINCT territory_name, region_name
                FROM zip_territory
                WHERE zip = :name
                """,
                {"name": reference.name},
            )
        return None


def _state_predicate(state: str) -> tuple[str, dict[str, str]]:
    return (
        """
        SELECT DISTINCT territory_name, region_name
        FROM zip_territory
        WHERE state = :state
        """,
        {"state": state},
    )


def _state_code(value: str) -> str | None:
    normalized = re.sub(r"[^a-z]+", " ", value.casefold()).strip()
    if len(normalized) == 2:
        return normalized.upper()
    return STATE_CODES.get(normalized)


def _same_name(left: str | None, right: str | None) -> bool:
    if left is None or right is None:
        return False

    def normalize(value: str) -> str:
        return re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()

    return normalize(left) == normalize(right)
