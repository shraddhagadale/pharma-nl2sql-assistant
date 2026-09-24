from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class UserRole(StrEnum):
    EXEC = "exec"
    DIRECTOR = "director"
    RAM = "ram"


class UserContext(BaseModel):
    model_config = ConfigDict(frozen=True)

    user_id: str
    email: str
    full_name: str
    role: UserRole
    territory_name: str | None
    region_name: str | None
    can_view_wac: bool


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: str = Field(min_length=1, max_length=64)


class AnalyticsOverview(BaseModel):
    user: UserContext
    period_months: int
    transaction_count: int
    organization_count: int
    pack_units: Decimal
    total_mg: Decimal
    revenue: Decimal | None
    revenue_visible: bool
    assumptions: list[str]


class ConversationRole(StrEnum):
    USER = "user"
    ASSISTANT = "assistant"


class ConversationTurn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: ConversationRole
    content: str = Field(min_length=1, max_length=1_000)


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=1, max_length=2_000)
    conversation: list[ConversationTurn] = Field(default_factory=list, max_length=6)
    include_sql: bool = False


class ChatStatus(StrEnum):
    ANSWERED = "answered"
    DENIED = "denied"
    REJECTED = "rejected"


JsonScalar = str | int | float | bool | None


class ChatResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: ChatStatus
    answer: str
    columns: list[str] = Field(default_factory=list)
    rows: list[dict[str, JsonScalar]] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    sql: str | None = None
    request_id: str


class HealthResponse(BaseModel):
    status: str
