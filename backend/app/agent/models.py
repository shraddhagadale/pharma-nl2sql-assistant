from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.domain.models import DomainCatalog
from app.domain.selector import DomainSelection
from app.models import ConversationTurn, JsonScalar, UserContext


class AgentModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


type ParameterValue = str | int | float | bool


class QueryParameter(AgentModel):
    name: str = Field(pattern=r"^[a-z][a-z0-9_]{0,39}$")
    value: ParameterValue


class GeographyKind(StrEnum):
    CITY = "city"
    STATE = "state"
    TERRITORY = "territory"
    REGION = "region"
    ZIP = "zip"


class GeographyReference(AgentModel):
    kind: GeographyKind
    name: str = Field(min_length=1, max_length=120)
    state: str | None = Field(default=None, max_length=80)


class AnalyticsPlan(AgentModel):
    metric_id: str
    time_window_id: str
    comparison_time_window_ids: list[str]
    dimension_ids: list[str]
    filters: list[str]
    assumptions: list[str]
    geography: GeographyReference | None = None
    sql: str
    parameters: list[QueryParameter]

    @model_validator(mode="after")
    def validate_plan(self) -> "AnalyticsPlan":
        if not self.sql.strip():
            raise ValueError("sql must not be blank")
        if len(self.sql) > 12_000:
            raise ValueError("sql exceeds the maximum plan size")
        if len(self.parameters) > 20:
            raise ValueError("too many query parameters")
        if self.time_window_id in self.comparison_time_window_ids:
            raise ValueError("primary time window cannot also be a comparison window")
        if len(self.comparison_time_window_ids) != len(set(self.comparison_time_window_ids)):
            raise ValueError("comparison time windows must be unique")
        if len(self.comparison_time_window_ids) > 3:
            raise ValueError("too many comparison time windows")
        names = [parameter.name for parameter in self.parameters]
        if len(names) != len(set(names)):
            raise ValueError("query parameter names must be unique")
        if len(self.assumptions) > 8 or len(self.filters) > 12:
            raise ValueError("plan explanation is too large")
        return self

    @property
    def parameter_values(self) -> dict[str, ParameterValue]:
        return {parameter.name: parameter.value for parameter in self.parameters}


class AnswerSummary(AgentModel):
    answer: str
    notes: list[str]


class PlanningContext(AgentModel):
    question: str
    conversation: list[ConversationTurn]
    user: UserContext
    selection: DomainSelection
    schema_context: dict[str, list[str]]
    domain_context: dict[str, object]


class QueryResult(AgentModel):
    columns: list[str]
    rows: list[dict[str, JsonScalar]]


def build_domain_context(
    catalog: DomainCatalog,
    selection: DomainSelection,
) -> dict[str, object]:
    metric = catalog.metrics_by_id[selection.metric_ids[0]]
    related_metric_ids = {
        component.metric
        for component in (metric.numerator, metric.denominator)
        if component is not None
    }
    metrics = [metric, *(catalog.metrics_by_id[item] for item in sorted(related_metric_ids))]

    return {
        "metrics": [item.model_dump(mode="json", exclude={"sources"}) for item in metrics],
        "time_windows": [
            catalog.time_windows_by_id[item].model_dump(mode="json", exclude={"sources"})
            for item in [selection.time_window_id, *selection.comparison_time_window_ids]
        ],
        "dimensions": [
            catalog.dimensions_by_id[item].model_dump(mode="json", exclude={"sources"})
            for item in selection.dimension_ids
        ],
        "data_sources": [
            catalog.data_sources_by_id[item].model_dump(mode="json", exclude={"sources"})
            for item in selection.data_source_ids
        ],
    }
