from dataclasses import dataclass

from app.agent.provider import (
    OpenAIPlanningModel,
    PlanningModel,
    UnavailablePlanningModel,
)
from app.agent.workflow import AgentWorkflow
from app.audit import AuditLogger
from app.config import Settings
from app.db.pools import DatabasePools
from app.db.users import UserRepository
from app.domain.catalog import CatalogRepository
from app.services.analytics import AnalyticsService
from app.sql.executor import QueryExecutor
from app.sql.validator import SqlValidator


@dataclass(slots=True)
class Services:
    pools: DatabasePools
    users: UserRepository
    analytics: AnalyticsService
    agent: AgentWorkflow
    audit: AuditLogger

    @classmethod
    def build(
        cls,
        settings: Settings,
        planning_model: PlanningModel | None = None,
    ) -> "Services":
        pools = DatabasePools(settings)
        audit = AuditLogger()
        catalog = CatalogRepository.load(settings.domain_catalog_path)
        model = planning_model or cls._default_model(settings)
        return cls(
            pools=pools,
            users=UserRepository(pools),
            analytics=AnalyticsService(pools, audit),
            agent=AgentWorkflow(
                catalog=catalog,
                model=model,
                validator=SqlValidator(max_rows=settings.agent_max_rows),
                executor=QueryExecutor(pools),
                audit=audit,
                max_repairs=settings.agent_max_repairs,
            ),
            audit=audit,
        )

    @staticmethod
    def _default_model(settings: Settings) -> PlanningModel:
        if settings.openai_api_key is None:
            return UnavailablePlanningModel()
        return OpenAIPlanningModel(
            api_key=settings.openai_api_key,
            model=settings.openai_model,
        )
