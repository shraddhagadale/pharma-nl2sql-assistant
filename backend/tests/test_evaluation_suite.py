from pathlib import Path

from app.evaluation import run_evaluation

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_versioned_evaluation_suite_passes() -> None:
    report = run_evaluation(PROJECT_ROOT)

    assert report["total"] == 11
    assert report["failed"] == 0, report["results"]
