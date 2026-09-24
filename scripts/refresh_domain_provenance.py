#!/usr/bin/env python3
import argparse
import sys
from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

from app.domain.markdown import section_sha256


def _yaml_scalar(line: str) -> str:
    return str(yaml.safe_load(line.split(":", 1)[1].strip()))


def refresh(catalog_path: Path, *, write: bool) -> int:
    lines = catalog_path.read_text(encoding="utf-8").splitlines(keepends=True)
    current_path: str | None = None
    current_heading: str | None = None
    changes: list[tuple[int, str]] = []

    for index, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("- path:"):
            current_path = _yaml_scalar(stripped[2:])
            current_heading = None
        elif stripped.startswith("heading:") and current_path:
            current_heading = _yaml_scalar(stripped)
        elif (
            stripped.startswith("section_sha256:") and current_path and current_heading
        ):
            document = (PROJECT_ROOT / current_path).resolve()
            docs_root = (PROJECT_ROOT / "docs").resolve()
            try:
                document.relative_to(docs_root)
            except ValueError as error:
                raise ValueError(
                    f"provenance path escapes docs/: {current_path}"
                ) from error
            digest = section_sha256(document, current_heading)
            existing = _yaml_scalar(stripped)
            if existing != digest:
                indent = line[: len(line) - len(line.lstrip())]
                newline = "\n" if line.endswith("\n") else ""
                lines[index] = f'{indent}section_sha256: "{digest}"{newline}'
                changes.append((index + 1, f"{current_path}#{current_heading}"))
            current_path = None
            current_heading = None

    if not changes:
        print("Domain provenance is current.")
        return 0
    if not write:
        print(f"{len(changes)} provenance digest(s) need refresh:", file=sys.stderr)
        for line_number, reference in changes:
            print(f"- line {line_number}: {reference}", file=sys.stderr)
        print("Review the source changes, then rerun with --write.", file=sys.stderr)
        return 1

    catalog_path.write_text("".join(lines), encoding="utf-8")
    print(f"Refreshed {len(changes)} provenance digest(s) in {catalog_path}.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Refresh domain-catalog hashes after reviewed Markdown changes"
    )
    parser.add_argument(
        "catalog",
        nargs="?",
        type=Path,
        default=PROJECT_ROOT / "domain" / "domain_catalog.yaml",
    )
    parser.add_argument(
        "--write",
        action="store_true",
        help="write refreshed hashes; without this flag the command is a read-only check",
    )
    args = parser.parse_args()
    return refresh(args.catalog.resolve(), write=args.write)


if __name__ == "__main__":
    raise SystemExit(main())
