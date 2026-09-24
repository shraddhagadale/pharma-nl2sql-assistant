from dataclasses import dataclass

from app.audit import AuditLogger
from app.config import Settings
from app.db.pools import DatabasePools
from app.db.users import UserRepository
from app.services.analytics import AnalyticsService


@dataclass(slots=True)
class Services:
    pools: DatabasePools
    users: UserRepository
    analytics: AnalyticsService
    audit: AuditLogger

    @classmethod
    def build(cls, settings: Settings) -> "Services":
        pools = DatabasePools(settings)
        audit = AuditLogger()
        return cls(
            pools=pools,
            users=UserRepository(pools),
            analytics=AnalyticsService(pools, audit),
            audit=audit,
        )
