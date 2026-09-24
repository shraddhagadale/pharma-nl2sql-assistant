import hashlib
import re
from pathlib import Path

HEADING_PATTERN = re.compile(r"^(#{1,6})\s+(.+?)\s*$")


def extract_section(document: Path, heading: str) -> str:
    lines = document.read_text(encoding="utf-8").splitlines()
    matches: list[tuple[int, int]] = []
    for index, line in enumerate(lines):
        match = HEADING_PATTERN.match(line)
        if match and match.group(2) == heading:
            matches.append((index, len(match.group(1))))

    if not matches:
        raise ValueError(f"heading {heading!r} not found in {document}")
    if len(matches) > 1:
        raise ValueError(f"heading {heading!r} is ambiguous in {document}")

    start, level = matches[0]
    end = len(lines)
    for index in range(start + 1, len(lines)):
        match = HEADING_PATTERN.match(lines[index])
        if match and len(match.group(1)) <= level:
            end = index
            break
    return "\n".join(lines[start:end]).strip() + "\n"


def section_sha256(document: Path, heading: str) -> str:
    section = extract_section(document, heading)
    return hashlib.sha256(section.encode("utf-8")).hexdigest()
