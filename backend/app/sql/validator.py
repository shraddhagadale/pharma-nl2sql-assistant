import hashlib
import re
from dataclasses import dataclass
from typing import Any

from sqlglot import exp, parse
from sqlglot.errors import ParseError

from app.agent.models import AnalyticsPlan, ParameterValue
from app.domain.models import DomainCatalog, FilterOperator, FilterRule, JoinRule
from app.domain.selector import DomainSelection
from app.models import UserRole
from app.sql.schema import ANALYTICS_SCHEMA, role_safe_schema

ALLOWED_FUNCTIONS = {
    "ABS",
    "AVG",
    "CASE",
    "CAST",
    "COALESCE",
    "COUNT",
    "IF",
    "LOWER",
    "MAX",
    "MIN",
    "NULLIF",
    "ROUND",
    "SUM",
    "UPPER",
}
ALLOWED_STRING_LITERALS = {"distributor", "hub_dispense", "market_data"}
COMMENT_MARKERS = re.compile(r"--|/\*")
DISALLOWED_NODES = (
    exp.Alter,
    exp.Command,
    exp.Copy,
    exp.Create,
    exp.Delete,
    exp.Drop,
    exp.Grant,
    exp.Insert,
    exp.Into,
    exp.Lock,
    exp.Merge,
    exp.Revoke,
    exp.Transaction,
    exp.TruncateTable,
    exp.Update,
)


class SqlValidationError(ValueError):
    def __init__(self, issues: list[str]) -> None:
        self.issues = sorted(set(issues))
        super().__init__("SQL validation failed: " + "; ".join(self.issues))


@dataclass(frozen=True, slots=True)
class ValidatedQuery:
    sql: str
    parameters: dict[str, ParameterValue]
    fingerprint: str
    referenced_tables: tuple[str, ...]
    referenced_columns: tuple[str, ...]
    row_limit: int


class SqlValidator:
    def __init__(self, *, max_rows: int) -> None:
        self.max_rows = max_rows

    def validate(
        self,
        plan: AnalyticsPlan,
        *,
        role: UserRole,
        catalog: DomainCatalog,
        selection: DomainSelection,
    ) -> ValidatedQuery:
        issues = self._plan_alignment_issues(plan, selection)
        sql = plan.sql.strip()
        if COMMENT_MARKERS.search(sql):
            issues.append("SQL comments are not allowed")

        try:
            statements = parse(sql, read="postgres")
        except ParseError as error:
            description = error.errors[0]["description"]
            raise SqlValidationError([f"SQL parse error: {description}"]) from error

        if len(statements) != 1:
            issues.append("exactly one SQL statement is required")
        if not statements:
            raise SqlValidationError(issues or ["SQL is empty"])

        tree = statements[0]
        if not isinstance(tree, exp.Select):
            issues.append("only SELECT statements are allowed")
        for node_type in DISALLOWED_NODES:
            if tree.find(node_type):
                issues.append(f"{node_type.__name__} expressions are not allowed")

        if len(list(tree.find_all(exp.Join))) > 6:
            issues.append("query has too many joins")
        if len(list(tree.find_all(exp.CTE))) > 8:
            issues.append("query has too many CTEs")
        if len(list(tree.find_all(exp.Subquery))) > 8:
            issues.append("query has too many subqueries")

        cte_columns = {
            cte.alias_or_name: set(cte.this.named_selects) for cte in tree.find_all(exp.CTE)
        }
        aliases: dict[str, str] = {}
        cte_aliases: dict[str, str] = {}
        tables: set[str] = set()
        for table in tree.find_all(exp.Table):
            if table.name in cte_columns:
                cte_aliases[table.alias_or_name] = table.name
                continue
            if table.db or table.catalog:
                issues.append(f"schema-qualified table is not allowed: {table.sql()}")
                continue
            if table.name not in ANALYTICS_SCHEMA:
                issues.append(f"table is not allowed: {table.name}")
                continue
            tables.add(table.name)
            alias = table.alias_or_name
            if alias in aliases and aliases[alias] != table.name:
                issues.append(f"table alias is ambiguous: {alias}")
            aliases[alias] = table.name

        columns = {column.name for column in tree.find_all(exp.Column)}
        if role != UserRole.EXEC and "wac" in columns:
            issues.append("WAC is restricted to executives")

        safe_schema = role_safe_schema(role)
        visible_columns = {column for table in tables for column in safe_schema.get(table, [])}
        visible_columns.update(name for names in cte_columns.values() for name in names)
        visible_columns.update(alias.alias for alias in tree.find_all(exp.Alias) if alias.alias)

        for column in tree.find_all(exp.Column):
            if column.table:
                table_name = aliases.get(column.table)
                if table_name:
                    if column.name not in safe_schema[table_name]:
                        issues.append(f"column is not allowed: {column.sql()}")
                elif column.table in cte_aliases:
                    cte_name = cte_aliases[column.table]
                    if column.name not in cte_columns[cte_name]:
                        issues.append(f"unknown CTE column: {column.sql()}")
                else:
                    issues.append(f"unknown table alias: {column.table}")
            elif column.name not in visible_columns:
                issues.append(f"column is not allowed or unknown: {column.name}")

        for star in tree.find_all(exp.Star):
            if not isinstance(star.parent, exp.Count):
                issues.append("SELECT star is not allowed")

        for function in tree.find_all(exp.Func):
            if isinstance(function, exp.Connector):
                continue
            function_name = function.sql_name().upper()
            if function_name not in ALLOWED_FUNCTIONS:
                issues.append(f"function is not allowed: {function_name}")

        for join in tree.find_all(exp.Join):
            is_unbounded = join.args.get("on") is None and not join.args.get("using")
            if join.kind.upper() == "CROSS" or is_unbounded:
                issues.append("cross or unbounded joins are not allowed")

        placeholders = {placeholder.name for placeholder in tree.find_all(exp.Placeholder)}
        parameter_names = set(plan.parameter_values)
        if placeholders != parameter_names:
            issues.append(
                "SQL placeholders must exactly match plan parameters "
                f"(SQL={sorted(placeholders)}, parameters={sorted(parameter_names)})"
            )
        for parameter in plan.parameters:
            if isinstance(parameter.value, str) and len(parameter.value) > 200:
                issues.append(f"parameter value is too long: {parameter.name}")

        for literal in tree.find_all(exp.Literal):
            if literal.is_string and literal.this not in ALLOWED_STRING_LITERALS:
                issues.append(f"string literal must be a named parameter: {literal.this[:40]}")

        issues.extend(self._business_rule_issues(tree, catalog, selection))
        row_limit = self._enforce_limit(tree, issues)

        if issues:
            raise SqlValidationError(issues)

        normalized_sql = tree.sql(dialect="postgres", pretty=False)
        fingerprint = hashlib.sha256(normalized_sql.encode("utf-8")).hexdigest()
        return ValidatedQuery(
            sql=normalized_sql,
            parameters=plan.parameter_values,
            fingerprint=fingerprint,
            referenced_tables=tuple(sorted(tables)),
            referenced_columns=tuple(sorted(columns)),
            row_limit=row_limit,
        )

    @staticmethod
    def _plan_alignment_issues(
        plan: AnalyticsPlan,
        selection: DomainSelection,
    ) -> list[str]:
        issues: list[str] = []
        if plan.metric_id not in selection.metric_ids:
            issues.append(f"plan metric must be {selection.metric_ids[0]}")
        if plan.time_window_id != selection.time_window_id:
            issues.append(f"plan time window must be {selection.time_window_id}")
        if set(plan.comparison_time_window_ids) != set(selection.comparison_time_window_ids):
            issues.append("plan comparison time windows must exactly match the selection")
        if set(plan.dimension_ids) != set(selection.dimension_ids):
            issues.append("plan dimensions must exactly match the deterministic selection")
        return issues

    def _business_rule_issues(
        self,
        tree: exp.Select,
        catalog: DomainCatalog,
        selection: DomainSelection,
    ) -> list[str]:
        issues: list[str] = []
        metric = catalog.metrics_by_id[selection.metric_ids[0]]
        columns = {column.name for column in tree.find_all(exp.Column)}

        required_fields: set[str] = set()
        required_filters = [*metric.filters]
        required_joins = [*metric.joins]
        if metric.field:
            required_fields.add(metric.field.split(".", 1)[1])
        if metric.expression:
            required_fields.update(field.split(".", 1)[1] for field in metric.expression.fields)
        for component in (metric.numerator, metric.denominator):
            if component:
                required_filters.extend(component.filters)
                component_metric = catalog.metrics_by_id[component.metric]
                if component_metric.expression:
                    required_fields.update(
                        field.split(".", 1)[1] for field in component_metric.expression.fields
                    )
                required_joins.extend(component_metric.joins)

        for field in sorted(required_fields):
            if field not in columns:
                issues.append(f"metric {metric.id} requires column {field}")
        for filter_rule in required_filters:
            if not self._has_filter(tree, filter_rule):
                issues.append(
                    f"metric {metric.id} requires filter {filter_rule.field} "
                    f"{filter_rule.operator.value} {filter_rule.value}"
                )

        for data_source_id in selection.data_source_ids:
            data_source = catalog.data_sources_by_id[data_source_id]
            rule = FilterRule(
                field="sales.data_source",
                operator=FilterOperator.EQ,
                value=data_source.value,
            )
            if not self._has_filter(tree, rule):
                issues.append(
                    f"selected data source {data_source_id} requires "
                    f"sales.data_source = {data_source.value}"
                )

        for window_id in [selection.time_window_id, *selection.comparison_time_window_ids]:
            window = catalog.time_windows_by_id[window_id]
            required_occurrences = 2 if metric.kind.value == "ratio" else 1
            if self._filter_count(tree, window.filter) < required_occurrences:
                issues.append(
                    f"time window {window.id} requires {window.filter.field} "
                    f"{window.filter.operator.value} {window.filter.value} in each metric component"
                )

        for dimension_id in selection.dimension_ids:
            dimension = catalog.dimensions_by_id[dimension_id]
            required_joins.extend(dimension.joins)
            for field in dimension.expression.fields:
                column_name = field.split(".", 1)[1]
                if column_name not in columns:
                    issues.append(f"dimension {dimension_id} requires column {column_name}")

        for join_rule in required_joins:
            if not self._has_join(tree, join_rule):
                issues.append(f"required join is missing: {join_rule.left} = {join_rule.right}")

        if metric.kind.value == "ratio":
            if tree.find(exp.Div) is None:
                issues.append(f"ratio metric {metric.id} requires division")
            if metric.zero_denominator == "null" and not (
                tree.find(exp.Nullif) or tree.find(exp.Case)
            ):
                issues.append(f"ratio metric {metric.id} requires a NULL zero denominator")
        return issues

    @staticmethod
    def _has_filter(tree: exp.Select, rule: FilterRule) -> bool:
        return SqlValidator._filter_count(tree, rule) > 0

    @staticmethod
    def _filter_count(tree: exp.Select, rule: FilterRule) -> int:
        column_name = rule.field.split(".", 1)[1]
        expected = rule.value if isinstance(rule.value, list) else [rule.value]
        matches = 0

        if rule.operator.value == "eq":
            for node in tree.find_all(exp.EQ):
                if (
                    SqlValidator._column_name(node.this) == column_name
                    and SqlValidator._values(node.expression) == expected
                ):
                    matches += 1
        elif rule.operator.value == "lte":
            for node in tree.find_all(exp.LTE):
                if (
                    SqlValidator._column_name(node.this) == column_name
                    and SqlValidator._values(node.expression) == expected
                ):
                    matches += 1
        elif rule.operator.value == "in":
            for node in tree.find_all(exp.In):
                if SqlValidator._column_name(node.this) == column_name:
                    values = [SqlValidator._literal_value(item) for item in node.expressions]
                    if values == expected:
                        matches += 1
        elif rule.operator.value == "between":
            for node in tree.find_all(exp.Between):
                if SqlValidator._column_name(node.this) == column_name:
                    values = [
                        SqlValidator._literal_value(node.args["low"]),
                        SqlValidator._literal_value(node.args["high"]),
                    ]
                    if values == expected:
                        matches += 1
        return matches

    @staticmethod
    def _has_join(tree: exp.Select, rule: JoinRule) -> bool:
        aliases = {
            table.alias_or_name: table.name
            for table in tree.find_all(exp.Table)
            if not table.db and not table.catalog
        }
        left_table, left_column = rule.left.split(".", 1)
        right_table, right_column = rule.right.split(".", 1)
        required = {(left_table, left_column), (right_table, right_column)}

        for join in tree.find_all(exp.Join):
            condition = join.args.get("on")
            if condition is None:
                continue
            equalities = (
                [condition] if isinstance(condition, exp.EQ) else condition.find_all(exp.EQ)
            )
            for equality in equalities:
                if not isinstance(equality.this, exp.Column) or not isinstance(
                    equality.expression, exp.Column
                ):
                    continue
                actual = {
                    (aliases.get(column.table, column.table), column.name)
                    for column in (equality.this, equality.expression)
                }
                if actual == required:
                    return True
        return False

    @staticmethod
    def _column_name(node: exp.Expression) -> str | None:
        return node.name if isinstance(node, exp.Column) else None

    @staticmethod
    def _values(node: exp.Expression) -> list[Any]:
        return [SqlValidator._literal_value(node)]

    @staticmethod
    def _literal_value(node: exp.Expression) -> Any:
        if not isinstance(node, exp.Literal):
            return None
        if node.is_string:
            return node.this
        try:
            return int(node.this)
        except ValueError:
            try:
                return float(node.this)
            except ValueError:
                return node.this

    def _enforce_limit(self, tree: exp.Select, issues: list[str]) -> int:
        limit = tree.args.get("limit")
        if limit is None:
            tree.limit(self.max_rows, copy=False)
            return self.max_rows
        expression = limit.expression
        if not isinstance(expression, exp.Literal) or expression.is_string:
            issues.append("LIMIT must be a positive integer literal")
            return self.max_rows
        try:
            requested = int(expression.this)
        except ValueError:
            issues.append("LIMIT must be a positive integer literal")
            return self.max_rows
        if requested < 1:
            issues.append("LIMIT must be positive")
            return self.max_rows
        if requested > self.max_rows:
            tree.limit(self.max_rows, copy=False)
            return self.max_rows
        return requested
