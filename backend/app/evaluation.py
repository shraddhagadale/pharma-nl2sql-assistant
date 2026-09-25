import json
from pathlib import Path
from typing import Any

from app.agent.models import AnalyticsPlan, QueryParameter
from app.models import UserRole
from app.sql.validator import SqlValidationError, SqlValidator


def _load_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict) or value.get("version") != 1:
        raise ValueError(f"unsupported evaluation file: {path}")
    return value


def run_evaluation(project_root: Path) -> dict[str, Any]:
    validator = SqlValidator(max_rows=100)
    adversarial = _load_json(project_root / "evaluation" / "sql_policy_cases.json")
    results: list[dict[str, Any]] = []

    for case in adversarial["sql_cases"]:
        try:
            role = UserRole(case["role"])
            plan = AnalyticsPlan(
                metric_id=case.get("metric_id", "evaluation_metric"),
                time_window_id=case.get("time_window_id", "evaluation_window"),
                sql=case["sql"],
                parameters=[
                    QueryParameter.model_validate(item) for item in case.get("parameters", [])
                ],
            )
            expected = case["expected"]
            if expected["status"] == "accepted":
                validated = validator.validate(plan, role=role)
                if validated.row_limit != expected["row_limit"]:
                    raise AssertionError(
                        f"expected row_limit={expected['row_limit']}, got {validated.row_limit}"
                    )
            else:
                try:
                    validator.validate(plan, role=role)
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
