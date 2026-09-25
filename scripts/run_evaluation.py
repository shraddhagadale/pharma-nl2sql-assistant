#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

from app.evaluation import run_evaluation


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run the versioned SQL-policy evaluation"
    )
    parser.add_argument(
        "--json", action="store_true", help="print the complete JSON report"
    )
    args = parser.parse_args()

    report = run_evaluation(PROJECT_ROOT)
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(
            f"Evaluation: {report['passed']}/{report['total']} passed, "
            f"{report['failed']} failed."
        )
        for result in report["results"]:
            if result["status"] == "failed":
                print(f"- {result['suite']}/{result['id']}: {result['error']}")
    return 1 if report["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
