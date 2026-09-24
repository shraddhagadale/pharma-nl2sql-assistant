import re
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from app.domain.markdown import section_sha256
from app.domain.models import DomainCatalog, SourceReference

FIELD_REFERENCE = re.compile(r"^[a-z_][a-z0-9_]*\.[a-z_][a-z0-9_]*$")
CREATE_TABLE = re.compile(
    r"CREATE TABLE\s+([a-z_][a-z0-9_]*)\s*\((.*?)\);",
    re.IGNORECASE | re.DOTALL,
)
COLUMN_LINE = re.compile(r"^\s{4}([a-z_][a-z0-9_]*)\s+[a-z]", re.IGNORECASE)


class CatalogValidationError(ValueError):
    def __init__(self, issues: list[str]) -> None:
        self.issues = issues
        super().__init__("Domain catalog validation failed:\n- " + "\n- ".join(issues))


class CatalogRepository:
    @classmethod
    def load(
        cls,
        catalog_path: Path,
        *,
        project_root: Path | None = None,
    ) -> DomainCatalog:
        resolved_path = catalog_path.resolve()
        root = (project_root or resolved_path.parent.parent).resolve()
        try:
            raw = yaml.safe_load(resolved_path.read_text(encoding="utf-8"))
            catalog = DomainCatalog.model_validate(raw)
        except (OSError, yaml.YAMLError, ValidationError) as error:
            raise CatalogValidationError([str(error)]) from error

        issues = CatalogValidator(root).validate(catalog)
        if issues:
            raise CatalogValidationError(issues)
        return catalog


class CatalogValidator:
    def __init__(self, project_root: Path) -> None:
        self.project_root = project_root.resolve()

    def validate(self, catalog: DomainCatalog) -> list[str]:
        issues: list[str] = []
        schema = self._load_schema(catalog.schema_source, issues)
        metric_ids = set(catalog.metrics_by_id)
        data_source_ids = set(catalog.data_sources_by_id)

        if catalog.defaults.metric not in metric_ids:
            issues.append(f"unknown default metric: {catalog.defaults.metric}")
        if catalog.defaults.time_window not in catalog.time_windows_by_id:
            issues.append(f"unknown default time window: {catalog.defaults.time_window}")
        if catalog.defaults.account_dimension not in catalog.dimensions_by_id:
            issues.append(
                f"unknown default account dimension: {catalog.defaults.account_dimension}"
            )

        for metric in catalog.metrics:
            if metric.alternative_metric and metric.alternative_metric not in metric_ids:
                issues.append(
                    f"metric {metric.id} has unknown alternative {metric.alternative_metric}"
                )
            if metric.numerator and metric.numerator.metric not in metric_ids:
                issues.append(f"metric {metric.id} has unknown numerator {metric.numerator.metric}")
            if metric.denominator and metric.denominator.metric not in metric_ids:
                issues.append(
                    f"metric {metric.id} has unknown denominator {metric.denominator.metric}"
                )
            for source_id in metric.data_sources:
                if source_id not in data_source_ids:
                    issues.append(f"metric {metric.id} has unknown data source {source_id}")

        for rule in catalog.security_rules:
            if rule.alternative_metric and rule.alternative_metric not in metric_ids:
                issues.append(
                    f"security rule {rule.id} has unknown alternative {rule.alternative_metric}"
                )

        for reference in self._field_references(catalog):
            if not FIELD_REFERENCE.fullmatch(reference):
                issues.append(f"invalid field reference: {reference}")
                continue
            table, column = reference.split(".", 1)
            if table not in schema:
                issues.append(f"unknown table in field reference: {reference}")
            elif column not in schema[table]:
                issues.append(f"unknown column in field reference: {reference}")

        for source in self._source_references(catalog):
            issues.extend(self._validate_source(source))
        return sorted(set(issues))

    def _load_schema(self, relative_path: str, issues: list[str]) -> dict[str, set[str]]:
        path = self._safe_path(relative_path, allowed_prefix="schema")
        if path is None or not path.is_file():
            issues.append(f"schema source does not exist: {relative_path}")
            return {}
        sql = path.read_text(encoding="utf-8")
        schema: dict[str, set[str]] = {}
        for table_match in CREATE_TABLE.finditer(sql):
            columns = {
                match.group(1)
                for line in table_match.group(2).splitlines()
                if (match := COLUMN_LINE.match(line))
                and match.group(1).upper() not in {"CONSTRAINT", "CHECK", "FOREIGN"}
            }
            schema[table_match.group(1)] = columns
        if not schema:
            issues.append(f"no CREATE TABLE definitions found in {relative_path}")
        return schema

    def _validate_source(self, source: SourceReference) -> list[str]:
        path = self._safe_path(source.path, allowed_prefix="docs")
        if path is None or path.suffix.lower() != ".md" or not path.is_file():
            return [f"invalid provenance path: {source.path}"]
        try:
            actual_digest = section_sha256(path, source.heading)
        except ValueError as error:
            return [str(error)]
        if actual_digest != source.section_sha256:
            return [
                f"stale provenance for {source.path}#{source.heading}: "
                f"expected {source.section_sha256}, actual {actual_digest}"
            ]
        return []

    def _safe_path(self, relative_path: str, *, allowed_prefix: str) -> Path | None:
        candidate = (self.project_root / relative_path).resolve()
        allowed_root = (self.project_root / allowed_prefix).resolve()
        try:
            candidate.relative_to(allowed_root)
        except ValueError:
            return None
        return candidate

    @staticmethod
    def _source_references(catalog: DomainCatalog) -> list[SourceReference]:
        definitions: list[Any] = [
            *catalog.metrics,
            *catalog.time_windows,
            *catalog.dimensions,
            *catalog.data_sources,
            *catalog.security_rules,
        ]
        return [source for definition in definitions for source in definition.sources]

    @staticmethod
    def _field_references(catalog: DomainCatalog) -> set[str]:
        references: set[str] = set()
        for metric in catalog.metrics:
            if metric.field:
                references.add(metric.field)
            if metric.expression:
                references.update(metric.expression.fields)
            references.update(rule.field for rule in metric.filters)
            for join in metric.joins:
                references.update((join.left, join.right))
            for component in (metric.numerator, metric.denominator):
                if component:
                    references.update(rule.field for rule in component.filters)
        for window in catalog.time_windows:
            references.add(window.filter.field)
        for dimension in catalog.dimensions:
            references.update(dimension.expression.fields)
            for join in dimension.joins:
                references.update((join.left, join.right))
        for rule in catalog.security_rules:
            if rule.protected_field:
                references.add(rule.protected_field)
        return references
