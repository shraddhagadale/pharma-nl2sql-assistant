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


class HealthResponse(BaseModel):
    status: str
