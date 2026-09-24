import re
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from app.domain.models import DomainCatalog
from app.models import UserRole


class SelectionStatus(StrEnum):
    ALLOWED = "allowed"
    DENIED = "denied"


class DomainSelection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    status: SelectionStatus
    metric_ids: list[str]
    time_window_id: str
    comparison_time_window_ids: list[str] = Field(default_factory=list)
    dimension_ids: list[str]
    data_source_ids: list[str]
    denied_reason: str | None = None
    alternative_metric_id: str | None = None


class DomainRuleSelector:
    def __init__(self, catalog: DomainCatalog) -> None:
        self.catalog = catalog

    def select(
        self,
        question: str,
        *,
        role: UserRole,
        context_question: str | None = None,
    ) -> DomainSelection:
        normalized = self._normalize(question)
        if not normalized:
            raise ValueError("question must not be blank")
        normalized_context = self._normalize(context_question or "")

        metrics = self._matching_definitions(normalized, self.catalog.metrics)[:1]
        if not metrics and normalized_context:
            metrics = self._matching_definitions(normalized_context, self.catalog.metrics)[:1]
        if not metrics:
            metrics = [self.catalog.metrics_by_id[self.catalog.defaults.metric]]

        windows = self._matching_definitions(normalized, self.catalog.time_windows)
        if not windows and normalized_context:
            windows = self._matching_definitions(normalized_context, self.catalog.time_windows)
        time_window_id = windows[0].id if windows else self.catalog.defaults.time_window
        comparison_time_window_ids = [window.id for window in windows[1:]]
        dimensions = self._matching_definitions(normalized, self.catalog.dimensions)
        if not dimensions and normalized_context:
            dimensions = self._matching_definitions(normalized_context, self.catalog.dimensions)

        denied_metric = next(
            (metric for metric in metrics if metric.requires_wac and role != UserRole.EXEC),
            None,
        )
        data_source_ids = self._ordered_unique(
            source_id for metric in metrics for source_id in metric.data_sources
        )

        if denied_metric:
            return DomainSelection(
                status=SelectionStatus.DENIED,
                metric_ids=[metric.id for metric in metrics],
                time_window_id=time_window_id,
                comparison_time_window_ids=comparison_time_window_ids,
                dimension_ids=[dimension.id for dimension in dimensions],
                data_source_ids=data_source_ids,
                denied_reason="WAC-derived revenue is available only to executives.",
                alternative_metric_id=denied_metric.alternative_metric,
            )

        return DomainSelection(
            status=SelectionStatus.ALLOWED,
            metric_ids=[metric.id for metric in metrics],
            time_window_id=time_window_id,
            comparison_time_window_ids=comparison_time_window_ids,
            dimension_ids=[dimension.id for dimension in dimensions],
            data_source_ids=data_source_ids,
        )

    @classmethod
    def _matching_definitions(cls, normalized: str, definitions: list) -> list:
        matches: list[tuple[int, object]] = []
        for definition in definitions:
            score = max(
                (
                    len(cls._normalize(synonym))
                    for synonym in definition.synonyms
                    if cls._contains_phrase(normalized, cls._normalize(synonym))
                ),
                default=0,
            )
            if score:
                matches.append((score, definition))
        return [item for _, item in sorted(matches, key=lambda pair: (-pair[0], pair[1].id))]

    @staticmethod
    def _contains_phrase(normalized: str, phrase: str) -> bool:
        return f" {phrase} " in f" {normalized} "

    @staticmethod
    def _normalize(value: str) -> str:
        return re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()

    @staticmethod
    def _ordered_unique(values) -> list[str]:
        return list(dict.fromkeys(values))
