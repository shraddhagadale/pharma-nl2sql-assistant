import hashlib
import re
from dataclasses import dataclass

from sqlglot import exp, parse
from sqlglot.errors import ParseError

from app.agent.models import AnalyticsPlan, ParameterValue
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
    product_lookups: tuple[tuple[str, str], ...]
    row_limit: int


class SqlValidator:
    def __init__(self, *, max_rows: int) -> None:
        self.max_rows = max_rows

    def validate(
        self,
        plan: AnalyticsPlan,
        *,
        role: UserRole,
    ) -> ValidatedQuery:
        issues: list[str] = []
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

        row_limit = self._enforce_limit(tree, issues)
        product_lookups = self._product_lookups(tree)

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
            product_lookups=product_lookups,
            row_limit=row_limit,
        )

    @staticmethod
    def _product_lookups(tree: exp.Select) -> tuple[tuple[str, str], ...]:
        lookups: set[tuple[str, str]] = set()
        for comparison in tree.find_all(exp.EQ):
            product_columns = {
                column.name
                for column in comparison.find_all(exp.Column)
                if column.name in {"drug_name", "ndc"}
            }
            placeholders = {item.name for item in comparison.find_all(exp.Placeholder)}
            if len(product_columns) == 1:
                column_name = next(iter(product_columns))
                lookups.update((column_name, name) for name in placeholders)
        return tuple(sorted(lookups))

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
