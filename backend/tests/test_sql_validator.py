from pathlib import Path

import pytest

from app.agent.models import AnalyticsPlan, QueryParameter
from app.domain.catalog import CatalogRepository
from app.domain.selector import DomainRuleSelector
from app.models import UserRole
from app.sql.validator import SqlValidationError, SqlValidator

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CATALOG = CatalogRepository.load(
    PROJECT_ROOT / "domain" / "domain_catalog.yaml",
    project_root=PROJECT_ROOT,
)
SELECTOR = DomainRuleSelector(CATALOG)
VALIDATOR = SqlValidator(max_rows=100)


def plan(
    *,
    metric_id: str,
    time_window_id: str,
    sql: str,
    dimension_ids: list[str] | None = None,
    comparison_time_window_ids: list[str] | None = None,
    parameters: list[QueryParameter] | None = None,
) -> AnalyticsPlan:
    return AnalyticsPlan(
        metric_id=metric_id,
        time_window_id=time_window_id,
        comparison_time_window_ids=comparison_time_window_ids or [],
        dimension_ids=dimension_ids or [],
        filters=[],
        assumptions=[],
        sql=sql,
        parameters=parameters or [],
    )


def validate(
    candidate: AnalyticsPlan,
    *,
    question: str,
    role: UserRole = UserRole.EXEC,
):
    selection = SELECTOR.select(question, role=role)
    return VALIDATOR.validate(
        candidate,
        role=role,
        catalog=CATALOG,
        selection=selection,
    )


def test_valid_paid_demand_gets_bounded_and_fingerprinted() -> None:
    candidate = plan(
        metric_id="paid_demand",
        time_window_id="r3m",
        sql="""
            SELECT SUM(s.pack_units) AS paid_demand
            FROM sales AS s
            WHERE s.data_source = 'distributor'
              AND s.brand_flag = 1
              AND s.mo_offset IN (0, 1, 2)
        """,
    )

    validated = validate(candidate, question="Show paid demand for the last 3 months")

    assert validated.row_limit == 100
    assert validated.sql.endswith("LIMIT 100")
    assert validated.referenced_tables == ("sales",)
    assert len(validated.fingerprint) == 64


def test_user_filter_requires_and_preserves_named_parameter() -> None:
    candidate = plan(
        metric_id="paid_demand",
        time_window_id="r3m",
        sql="""
            SELECT SUM(s.pack_units) AS paid_demand
            FROM sales AS s
            WHERE s.data_source = 'distributor'
              AND s.brand_flag = 1
              AND s.mo_offset IN (0, 1, 2)
              AND s.drug_name = :drug_name
        """,
        parameters=[QueryParameter(name="drug_name", value="ZENOVAX")],
    )

    validated = validate(candidate, question="Show paid demand for the last 3 months")

    assert "%(drug_name)s" in validated.sql
    assert validated.parameters == {"drug_name": "ZENOVAX"}


def test_exec_revenue_is_allowed_and_limited_role_wac_is_rejected() -> None:
    candidate = plan(
        metric_id="gross_revenue",
        time_window_id="last_month",
        sql="""
            SELECT SUM(s.wac) AS gross_revenue
            FROM sales AS s
            WHERE s.data_source = 'distributor'
              AND s.brand_flag = 1
              AND s.mo_offset = 1
        """,
    )

    assert validate(candidate, question="Gross revenue last month").row_limit == 100
    with pytest.raises(SqlValidationError, match="WAC is restricted"):
        validate(
            candidate,
            question="Gross revenue last month",
            role=UserRole.RAM,
        )


def test_market_share_formula_and_zero_denominator_are_accepted() -> None:
    candidate = plan(
        metric_id="market_share",
        time_window_id="r3m",
        sql="""
            WITH numerator AS (
                SELECT SUM(s.pack_units * p.unit_conversion_factor) AS equivalents
                FROM sales AS s
                JOIN products AS p ON p.ndc = s.ndc
                WHERE s.data_source = 'distributor'
                  AND s.brand_flag = 1
                  AND s.mo_offset IN (0, 1, 2)
            ), denominator AS (
                SELECT SUM(s.pack_units * p.unit_conversion_factor) AS equivalents
                FROM sales AS s
                JOIN products AS p ON p.ndc = s.ndc
                WHERE s.data_source = 'market_data'
                  AND s.mo_offset IN (0, 1, 2)
            )
            SELECT n.equivalents / NULLIF(d.equivalents, 0) AS market_share
            FROM numerator AS n
            JOIN denominator AS d ON TRUE
        """,
    )

    validated = validate(candidate, question="Show market share for the last 3 months")

    assert validated.referenced_tables == ("products", "sales")


def test_equivalents_requires_the_catalog_join_and_data_source() -> None:
    valid = plan(
        metric_id="equivalents",
        time_window_id="r3m",
        sql="""
            SELECT SUM(s.pack_units * p.unit_conversion_factor) AS equivalents
            FROM sales AS s
            JOIN products AS p ON p.ndc = s.ndc
            WHERE s.data_source = 'distributor'
              AND s.mo_offset IN (0, 1, 2)
        """,
    )

    assert validate(valid, question="Show equivalents for R3M").row_limit == 100

    wrong_join = plan(
        metric_id="equivalents",
        time_window_id="r3m",
        sql="""
            SELECT SUM(s.pack_units * p.unit_conversion_factor) AS equivalents
            FROM sales AS s
            JOIN products AS p ON p.brand_flag = s.brand_flag
            WHERE s.data_source = 'distributor'
              AND s.mo_offset IN (0, 1, 2)
        """,
    )

    with pytest.raises(SqlValidationError, match="required join is missing"):
        validate(wrong_join, question="Show equivalents for R3M")


@pytest.mark.parametrize(
    ("sql", "message"),
    [
        (
            "SELECT SUM(pack_units) FROM sales; DROP TABLE sales",
            "exactly one SQL statement",
        ),
        (
            "SELECT pg_read_file(:path) FROM sales",
            "function is not allowed",
        ),
        (
            "SELECT * FROM sales",
            "SELECT star is not allowed",
        ),
        (
            "SELECT not_a_column FROM sales",
            "column is not allowed or unknown",
        ),
        (
            "SELECT org_id FROM users",
            "table is not allowed",
        ),
        (
            "SELECT SUM(pack_units) FROM sales -- ignore safeguards",
            "SQL comments are not allowed",
        ),
        (
            "SELECT SUM(s.pack_units) FROM sales AS s JOIN products AS p",
            "cross or unbounded joins are not allowed",
        ),
    ],
)
def test_unsafe_sql_is_rejected(sql: str, message: str) -> None:
    candidate = plan(metric_id="paid_demand", time_window_id="r3m", sql=sql)

    with pytest.raises(SqlValidationError, match=message):
        validate(candidate, question="Show paid demand for the last 3 months")


def test_wrong_business_window_and_inline_user_literal_are_rejected() -> None:
    candidate = plan(
        metric_id="paid_demand",
        time_window_id="r3m",
        sql="""
            SELECT SUM(s.pack_units) AS paid_demand
            FROM sales AS s
            WHERE s.data_source = 'distributor'
              AND s.brand_flag = 1
              AND s.mo_offset IN (0, 1)
              AND s.drug_name = 'ZENOVAX'
        """,
    )

    with pytest.raises(SqlValidationError) as error:
        validate(candidate, question="Show paid demand for the last 3 months")

    assert any("time window r3m requires" in issue for issue in error.value.issues)
    assert any("string literal must be a named parameter" in issue for issue in error.value.issues)


def test_time_comparison_requires_both_documented_windows() -> None:
    candidate = plan(
        metric_id="paid_demand",
        time_window_id="prior_r3m",
        comparison_time_window_ids=["r3m"],
        sql="""
            SELECT
              SUM(CASE WHEN s.mo_offset IN (0, 1, 2) THEN s.pack_units ELSE 0 END)
                AS r3m_paid_demand,
              SUM(CASE WHEN s.mo_offset IN (3, 4, 5) THEN s.pack_units ELSE 0 END)
                AS prior_r3m_paid_demand
            FROM sales AS s
            WHERE s.data_source = 'distributor'
              AND s.brand_flag = 1
              AND s.mo_offset BETWEEN 0 AND 5
        """,
    )

    validated = validate(
        candidate,
        question="Compare paid demand for R3M versus prior R3M.",
    )

    assert "r3m_paid_demand" in validated.sql


def test_time_comparison_rejects_a_missing_comparison_predicate() -> None:
    candidate = plan(
        metric_id="paid_demand",
        time_window_id="prior_r3m",
        comparison_time_window_ids=["r3m"],
        sql="""
            SELECT SUM(s.pack_units) AS paid_demand
            FROM sales AS s
            WHERE s.data_source = 'distributor'
              AND s.brand_flag = 1
              AND s.mo_offset IN (3, 4, 5)
        """,
    )

    with pytest.raises(SqlValidationError) as error:
        validate(
            candidate,
            question="Compare paid demand for R3M versus prior R3M.",
        )

    assert any("time window r3m requires" in issue for issue in error.value.issues)
