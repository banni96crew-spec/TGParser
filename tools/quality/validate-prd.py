#!/usr/bin/env python3
"""Deterministic product PRD validator; Python standard library only."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from urllib.parse import unquote

CONTRACT_VERSION = "1.0.0"
REQUIREMENT = re.compile(
    r"^(?:###\s+|\|\s*`?)([A-Z]{2,5}-\d{3})(?:\s+—|`?\s*\|)"
)
ACCEPTANCE = re.compile(
    r"^\|\s*`?(AT-([A-Z]{2,5})-(\d{3}))`?\s*\|\s*([^|]+)"
)
DECISION_DEFINITION = re.compile(r"^\|\s*(D-\d{3})\s*\|")
DECISION_REFERENCE = re.compile(r"\b(?:D|DEC)-\d{3}\b")
LINK = re.compile(r"\[[^\]]+]\(([^)]+)\)")
RANGE = re.compile(r"\b(AT-)?([A-Z]{2,5})-(\d{3})\.\.(\d{3})\b")


def strip_fenced_code(text: str) -> str:
    output: list[str] = []
    inside = False
    for line in text.splitlines():
        if line.lstrip().startswith("```"):
            inside = not inside
            continue
        if not inside:
            output.append(line)
    return "\n".join(output)


def relative(root: Path, file_path: Path) -> str:
    return file_path.relative_to(root).as_posix()


def expand_traceability(text: str) -> set[str]:
    result: set[str] = set()
    for match in RANGE.finditer(text):
        acceptance, prefix, start, end = match.groups()
        for number in range(int(start), int(end) + 1):
            result.add(f"{acceptance or ''}{prefix}-{number:03d}")
    return result


def validate(root: Path) -> dict[str, object]:
    errors: list[str] = []
    agents = root / "AGENTS.md"
    prd_root = root / "docs" / "prd"
    files = [agents, *sorted(prd_root.rglob("*.md"))]
    texts = {file_path: strip_fenced_code(file_path.read_text(encoding="utf-8")) for file_path in files}

    requirement_definitions: dict[str, str] = {}
    acceptance_definitions: dict[str, tuple[str, str]] = {}
    decision_definitions: set[str] = set()

    for file_path, text in texts.items():
        file_name = relative(root, file_path)
        for line_number, line in enumerate(text.splitlines(), start=1):
            requirement_match = REQUIREMENT.match(line)
            if requirement_match:
                requirement_id = requirement_match.group(1)
                location = f"{file_name}:{line_number}"
                if requirement_id in requirement_definitions:
                    errors.append(
                        f"duplicate requirement definition {requirement_id}: "
                        f"{requirement_definitions[requirement_id]}, {location}"
                    )
                else:
                    requirement_definitions[requirement_id] = location
            acceptance_match = ACCEPTANCE.match(line)
            if acceptance_match:
                acceptance_id, prefix, number, requirement_cell = acceptance_match.groups()
                expected_requirement = f"{prefix}-{number}"
                referenced = re.findall(r"\b[A-Z]{2,5}-\d{3}\b", requirement_cell)
                location = f"{file_name}:{line_number}"
                if acceptance_id in acceptance_definitions:
                    errors.append(f"duplicate acceptance definition {acceptance_id}: {location}")
                mapped_requirement = referenced[0] if referenced else expected_requirement
                acceptance_definitions[acceptance_id] = (mapped_requirement, location)
                if referenced and referenced != [expected_requirement]:
                    errors.append(
                        f"{acceptance_id} must reference exactly {expected_requirement}: {location}"
                    )
            decision_match = DECISION_DEFINITION.match(line)
            if decision_match:
                decision_id = decision_match.group(1)
                if decision_id in decision_definitions:
                    errors.append(f"duplicate decision definition {decision_id}: {file_name}:{line_number}")
                decision_definitions.add(decision_id)

    for requirement_id, location in sorted(requirement_definitions.items()):
        acceptance_id = f"AT-{requirement_id}"
        if acceptance_id not in acceptance_definitions:
            errors.append(f"missing acceptance definition {acceptance_id} for {location}")
    for acceptance_id, (requirement_id, location) in sorted(acceptance_definitions.items()):
        if requirement_id not in requirement_definitions:
            errors.append(f"{acceptance_id} references undefined {requirement_id}: {location}")

    for file_path, text in texts.items():
        if file_path.name == "DECISION_LOG.md":
            continue
        for raw_decision_id in sorted(set(DECISION_REFERENCE.findall(text))):
            decision_id = raw_decision_id.replace("DEC-", "D-")
            if decision_id not in decision_definitions:
                errors.append(
                    f"undefined decision reference {raw_decision_id}: {relative(root, file_path)}"
                )

    for file_path, text in texts.items():
        for target in LINK.findall(text):
            target_without_anchor = target.split("#", 1)[0]
            if not target_without_anchor or re.match(r"^(?:https?:|mailto:)", target_without_anchor):
                continue
            resolved = (file_path.parent / unquote(target_without_anchor)).resolve()
            if not resolved.exists():
                errors.append(
                    f"missing local link target {target}: {relative(root, file_path)}"
                )

    traceability_path = prd_root / "TRACEABILITY.md"
    covered = expand_traceability(texts[traceability_path])
    for requirement_id in sorted(requirement_definitions):
        if requirement_id not in covered:
            errors.append(f"TRACEABILITY missing {requirement_id}")
        acceptance_id = f"AT-{requirement_id}"
        if acceptance_id not in covered:
            errors.append(f"TRACEABILITY missing {acceptance_id}")

    errors.sort()
    return {
        "schema_version": CONTRACT_VERSION,
        "validator": "validate-prd",
        "status": "pass" if not errors else "fail",
        "errors": errors,
        "counts": {
            "acceptance_tests": len(acceptance_definitions),
            "decisions": len(decision_definitions),
            "files": len(files),
            "requirements": len(requirement_definitions),
        },
        "inputs": ["AGENTS.md", "docs/prd/**/*.md"],
    }


def main() -> int:
    root = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else Path.cwd().resolve()
    result = validate(root)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
