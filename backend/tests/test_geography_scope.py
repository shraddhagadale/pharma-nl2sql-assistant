import pytest

from app.agent.models import GeographyReference
from app.db.geography import GeographyScopeRepository
from app.db.pools import DatabasePools
from app.models import UserContext, UserRole


def user(role: UserRole) -> UserContext:
    return UserContext(
        user_id="U009" if role is UserRole.RAM else "U003",
        email="scope-test@example.test",
        full_name="Scope Test",
        role=role,
        territory_name="New York Metro" if role is UserRole.RAM else None,
        region_name="Northeast",
        can_view_wac=False,
    )


@pytest.mark.asyncio
async def test_reference_geography_is_compared_with_role_scope(settings) -> None:
    pools = DatabasePools(settings)
    repository = GeographyScopeRepository(pools)
    try:
        ram = user(UserRole.RAM)
        director = user(UserRole.DIRECTOR)

        assert await repository.is_within_scope(
            GeographyReference(kind="city", name="Albany", state="New York"),
            user=ram,
        )
        assert not await repository.is_within_scope(
            GeographyReference(kind="city", name="Springfield", state="Massachusetts"),
            user=ram,
        )
        assert await repository.is_within_scope(
            GeographyReference(kind="territory", name="New England"),
            user=director,
        )
        assert not await repository.is_within_scope(
            GeographyReference(kind="state", name="Texas"),
            user=director,
        )
    finally:
        await pools.dispose()
