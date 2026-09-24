#!/usr/bin/env python3
import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

from app.domain.catalog import CatalogRepository, CatalogValidationError


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate the curated domain catalog")
    parser.add_argument(
        "catalog",
        nargs="?",
        type=Path,
        default=PROJECT_ROOT / "domain" / "domain_catalog.yaml",
    )
    args = parser.parse_args()

    try:
        catalog = CatalogRepository.load(args.catalog, project_root=PROJECT_ROOT)
    except CatalogValidationError as error:
        print(error, file=sys.stderr)
        return 1

    print(
        "Domain catalog validated: "
        f"{len(catalog.metrics)} metrics, "
        f"{len(catalog.time_windows)} time windows, "
        f"{len(catalog.dimensions)} dimensions, "
        f"{len(catalog.data_sources)} data sources."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
