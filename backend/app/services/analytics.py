from decimal import Decimal
from time import perf_counter

from sqlalchemy import text

from app.audit import AuditEvent, AuditLogger
from app.db.pools import DatabasePools
from app.models import AnalyticsOverview, UserContext, UserRole

LIMITED_OVERVIEW = text(
    """
    SELECT
        COUNT(*)::bigint AS transaction_count,
        COUNT(DISTINCT org_id)::bigint AS organization_count,
        COALESCE(SUM(pack_units), 0) AS pack_units,
        COALESCE(SUM(total_mg), 0) AS total_mg
    FROM sales
    WHERE data_source = 'distributor'
      AND brand_flag = 1
      AND mo_offset < :months
    """
)

EXEC_OVERVIEW = text(
    """
    SELECT
        COUNT(*)::bigint AS transaction_count,
        COUNT(DISTINCT org_id)::bigint AS organization_count,
        COALESCE(SUM(pack_units), 0) AS pack_units,
        COALESCE(SUM(total_mg), 0) AS total_mg,
        COALESCE(SUM(wac), 0) AS revenue
    FROM sales
    WHERE data_source = 'distributor'
      AND brand_flag = 1
      AND mo_offset < :months
    """
)


class AnalyticsService:
    def __init__(self, pools: DatabasePools, audit: AuditLogger) -> None:
        self.pools = pools
        self.audit = audit

    async def overview(
        self,
        *,
        user: UserContext,
        months: int,
        request_id: str,
    ) -> AnalyticsOverview:
        started = perf_counter()
        access = self.pools.access_for_user(user)
        query = EXEC_OVERVIEW if user.role is UserRole.EXEC else LIMITED_OVERVIEW

        try:
            async with self.pools.transaction(access, user_id=user.user_id) as connection:
                row = (await connection.execute(query, {"months": months})).mappings().one()
        except Exception:
            self.audit.record(
                AuditEvent(
                    request_id=request_id,
                    user_id=user.user_id,
                    action="analytics.overview",
                    role=user.role.value,
                    outcome="error",
                    duration_ms=self._elapsed_ms(started),
                    row_count=0,
                    error_code="database_error",
                )
            )
            raise

        self.audit.record(
            AuditEvent(
                request_id=request_id,
                user_id=user.user_id,
                action="analytics.overview",
                role=user.role.value,
                outcome="success",
                duration_ms=self._elapsed_ms(started),
                row_count=1,
            )
        )

        return AnalyticsOverview(
            user=user,
            period_months=months,
            transaction_count=row["transaction_count"],
            organization_count=row["organization_count"],
            pack_units=Decimal(row["pack_units"]),
            total_mg=Decimal(row["total_mg"]),
            revenue=(Decimal(row["revenue"]) if "revenue" in row else None),
            revenue_visible=user.can_view_wac,
            assumptions=[
                "Paid demand uses distributor rows only.",
                "Only Nova-branded products are included.",
                f"The period uses mo_offset values 0 through {months - 1}.",
            ],
        )

    @staticmethod
    def _elapsed_ms(started: float) -> float:
        return round((perf_counter() - started) * 1_000, 3)
