from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator

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


class PlanDecision(StrEnum):
    QUERY = "query"
    CLARIFICATION = "clarification"
    DENIED = "denied"


class KnowledgeCitation(AgentModel):
    document: str = Field(min_length=1, max_length=120)
    heading: str = Field(min_length=1, max_length=200)


class GeographyReference(AgentModel):
    kind: GeographyKind
    name: str = Field(min_length=1, max_length=120)
    state: str | None = Field(default=None, max_length=80)


class AnalyticsPlan(AgentModel):
    decision: PlanDecision = PlanDecision.QUERY
    response: str | None = Field(default=None, max_length=500)
    resolved_question: str = Field(default="", max_length=2_000)
    evidence: list[KnowledgeCitation] = Field(default_factory=list, max_length=8)
    metric_id: str = Field(default="", max_length=120)
    time_window_id: str = Field(default="", max_length=120)
    comparison_time_window_ids: list[str] = Field(default_factory=list)
    dimension_ids: list[str] = Field(default_factory=list)
    filters: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    geography: GeographyReference | None = None
    sql: str = ""
    parameters: list[QueryParameter] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_plan(self) -> "AnalyticsPlan":
        if self.decision is PlanDecision.QUERY and not self.sql.strip():
            raise ValueError("query decisions require SQL")
        if self.decision is not PlanDecision.QUERY:
            if not self.response or not self.response.strip():
                raise ValueError("non-query decisions require a response")
            if self.sql.strip() or self.parameters:
                raise ValueError("non-query decisions cannot include SQL or parameters")
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
    schema_context: dict[str, list[str]]


class QueryResult(AgentModel):
    columns: list[str]
    rows: list[dict[str, JsonScalar]]
