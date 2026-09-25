from pathlib import Path
from typing import Any

import yaml

from app.agent.models import AnalyticsPlan, QueryParameter
from app.domain.catalog import CatalogRepository
from app.domain.selector import DomainRuleSelector
from app.models import UserRole
from app.sql.validator import SqlValidationError, SqlValidator


def _load_yaml(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        value = yaml.safe_load(handle)
    if not isinstance(value, dict) or value.get("version") != 1:
        raise ValueError(f"unsupported evaluation file: {path}")
    return value


def _matches_expected(actual: dict[str, Any], expected: dict[str, Any]) -> None:
    for key, expected_value in expected.items():
        if actual.get(key) != expected_value:
            raise AssertionError(f"expected {key}={expected_value!r}, got {actual.get(key)!r}")


def run_evaluation(project_root: Path) -> dict[str, Any]:
    catalog = CatalogRepository.load(
        project_root / "domain" / "domain_catalog.yaml",
        project_root=project_root,
    )
    selector = DomainRuleSelector(catalog)
    validator = SqlValidator(max_rows=100)
    golden = _load_yaml(project_root / "domain" / "golden_examples.yaml")
    adversarial = _load_yaml(project_root / "evaluation" / "adversarial_cases.yaml")

    results: list[dict[str, Any]] = []

    def evaluate_selection(case: dict[str, Any], suite: str) -> None:
        selection = selector.select(case["question"], role=UserRole(case["role"]))
        _matches_expected(selection.model_dump(mode="json"), case["expected"])
        results.append({"id": case["id"], "suite": suite, "status": "passed"})

    for case in golden["examples"]:
        try:
            evaluate_selection(case, "golden_selection")
        except Exception as error:
            results.append(
                {
                    "id": case["id"],
                    "suite": "golden_selection",
                    "status": "failed",
                    "error": str(error),
                }
            )

    for case in adversarial["selection_cases"]:
        try:
            evaluate_selection(case, "adversarial_selection")
        except Exception as error:
            results.append(
                {
                    "id": case["id"],
                    "suite": "adversarial_selection",
                    "status": "failed",
                    "error": str(error),
                }
            )

    for case in adversarial["sql_cases"]:
        try:
            role = UserRole(case["role"])
            selection = selector.select(case["question"], role=role)
            plan = AnalyticsPlan(
                metric_id=case.get("metric_id", selection.metric_ids[0]),
                time_window_id=case.get("time_window_id", selection.time_window_id),
                comparison_time_window_ids=case.get(
                    "comparison_time_window_ids",
                    selection.comparison_time_window_ids,
                ),
                dimension_ids=case.get("dimension_ids", selection.dimension_ids),
                filters=[],
                assumptions=[],
                sql=case["sql"],
                parameters=[
                    QueryParameter.model_validate(item) for item in case.get("parameters", [])
                ],
            )
            expected = case["expected"]
            if expected["status"] == "accepted":
                validated = validator.validate(
                    plan,
                    role=role,
                    catalog=catalog,
                    selection=selection,
                )
                if validated.row_limit != expected["row_limit"]:
                    raise AssertionError(
                        f"expected row_limit={expected['row_limit']}, got {validated.row_limit}"
                    )
            else:
                try:
                    validator.validate(
                        plan,
                        role=role,
                        catalog=catalog,
                        selection=selection,
                    )
                except SqlValidationError as error:
                    if expected["issue_contains"] not in str(error):
                        raise AssertionError(
                            f"missing validator issue {expected['issue_contains']!r}: {error}"
                        ) from error
                else:
                    raise AssertionError("unsafe SQL was accepted")
            results.append({"id": case["id"], "suite": "sql_policy", "status": "passed"})
        except Exception as error:
            results.append(
                {
                    "id": case["id"],
                    "suite": "sql_policy",
                    "status": "failed",
                    "error": str(error),
                }
            )

    passed = sum(result["status"] == "passed" for result in results)
    return {
        "total": len(results),
        "passed": passed,
        "failed": len(results) - passed,
        "results": results,
    }
