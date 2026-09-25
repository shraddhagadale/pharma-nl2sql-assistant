import re
from dataclasses import dataclass

from app.models import ChatStatus, UserContext, UserRole

from .models import AnalyticsPlan, GeographyKind, QueryResult

TECHNICAL_LANGUAGE = re.compile(
    r"\b(?:sql|query|rows?|null|database|rls|wac|validator|validated|data_source|"
    r"statement timeout|[a-z]+_[a-z_]+)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class OutcomeDecision:
    status: ChatStatus
    answer: str
    error_code: str


class ConversationOutcomeClassifier:
    @staticmethod
    def before_execution(
        plan: AnalyticsPlan,
        *,
        user: UserContext,
    ) -> OutcomeDecision | None:
        geography = plan.geography
        if geography is None:
            return None

        if geography.kind is GeographyKind.CITY and not geography.state:
            return OutcomeDecision(
                status=ChatStatus.CLARIFICATION,
                answer=f"Which state do you mean for {geography.name}?",
                error_code="ambiguous_geography",
            )

        if user.role is UserRole.RAM:
            if geography.kind is GeographyKind.REGION:
                return ConversationOutcomeClassifier.outside_scope(user)
            if geography.kind is GeographyKind.TERRITORY and not _same_name(
                geography.name,
                user.territory_name,
            ):
                return ConversationOutcomeClassifier.outside_scope(user)

        if (
            user.role is UserRole.DIRECTOR
            and geography.kind is GeographyKind.REGION
            and not _same_name(geography.name, user.region_name)
        ):
            return ConversationOutcomeClassifier.outside_scope(user)

        return None

    @staticmethod
    def classify_result(result: QueryResult) -> OutcomeDecision | None:
        if not result.rows or all(value is None for row in result.rows for value in row.values()):
            return OutcomeDecision(
                status=ChatStatus.NO_DATA,
                answer=(
                    "I couldn't find matching data within your available scope. "
                    "Try a different time period or filter."
                ),
                error_code="no_matching_data",
            )
        return None

    @staticmethod
    def classify_execution_error(error: Exception) -> OutcomeDecision:
        if _is_timeout(error):
            return OutcomeDecision(
                status=ChatStatus.ERROR,
                answer=(
                    "That analysis took too long to complete. Try a shorter time period "
                    "or add a product or account filter."
                ),
                error_code="query_timeout",
            )
        return OutcomeDecision(
            status=ChatStatus.ERROR,
            answer="I couldn't complete that analysis right now. Please try again.",
            error_code="database_error",
        )

    @staticmethod
    def is_business_friendly(value: str) -> bool:
        return TECHNICAL_LANGUAGE.search(value) is None

    @staticmethod
    def business_notes(values: list[str]) -> list[str]:
        return [
            value
            for value in values
            if value and ConversationOutcomeClassifier.is_business_friendly(value)
        ]

    @staticmethod
    def outside_scope(user: UserContext) -> OutcomeDecision:
        if user.territory_name:
            answer = (
                "That location is outside your assigned territory. "
                f"I can help with {user.territory_name} instead."
            )
        elif user.region_name:
            answer = (
                "That location is outside your assigned region. "
                f"I can help with {user.region_name} instead."
            )
        else:
            answer = "That location is outside your available scope."
        return OutcomeDecision(
            status=ChatStatus.DENIED,
            answer=answer,
            error_code="geography_scope",
        )


def _same_name(left: str | None, right: str | None) -> bool:
    if left is None or right is None:
        return False

    def normalize(value: str) -> str:
        return re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()

    return normalize(left) == normalize(right)


def _is_timeout(error: BaseException) -> bool:
    seen: set[int] = set()
    current: BaseException | None = error
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        code = getattr(current, "sqlstate", None) or getattr(current, "pgcode", None)
        if code == "57014":
            return True
        name = type(current).__name__.casefold()
        message = str(current).casefold()
        if "timeout" in name or "statement timeout" in message or "querycanceled" in name:
            return True
        current = current.__cause__ or current.__context__
    return False
