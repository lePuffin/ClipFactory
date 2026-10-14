#!/usr/bin/env python3
"""Report requirement IDs without a tagged automated test."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFINITION = re.compile(r"^### (CF-(?:REQ|NFR)-\d{3})\s+[—-]", re.MULTILINE)
TAG = re.compile(r"req\([\"'](CF-(?:REQ|NFR)-\d{3})[\"']\)")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--markdown-output", type=Path)
    args = parser.parse_args()
    specification_ids = {
        identifier
        for path in (ROOT / "doc/specifications").glob("*.md")
        for identifier in DEFINITION.findall(path.read_text(encoding="utf-8"))
    }
    tests = [* (ROOT / "backend/tests").rglob("*.py")]
    tested_ids = {identifier for path in tests for identifier in TAG.findall(path.read_text(encoding="utf-8"))}
    missing = sorted(specification_ids - tested_ids)
    print(f"Requirements defined: {len(specification_ids)}; tagged by tests: {len(specification_ids & tested_ids)}")
    if missing:
        print("Not yet covered:")
        print("\n".join(missing))
    if args.markdown_output:
        rows = []
        heading = re.compile(r"^### (CF-(?:REQ|NFR)-\d{3})\s+[—-]\s+(.+)$", re.MULTILINE)
        for path in sorted((ROOT / "doc/specifications").glob("*.md")):
            for identifier, title in heading.findall(path.read_text(encoding="utf-8")):
                evidence = [test for test in tests if identifier in TAG.findall(test.read_text(encoding="utf-8"))]
                links = ", ".join(f"[{test.name}](../../{test.relative_to(ROOT).as_posix()})" for test in evidence)
                rows.append(
                    f"| {identifier} | {title.replace('|', '/')} | [{path.name}](../specifications/{path.name}) | "
                    f"{'Tagged tests; not live verification' if evidence else 'No tagged test; not verified'} | {links or '-'} |"
                )
        text = [
            "# Requirements Evidence Inventory",
            "",
            "This inventories every canonical requirement and backend test tag. A tag does not prove that all acceptance criteria pass, that the implementation is complete, or that an integration has been verified live. The production review is recorded separately in [production-audit.md](production-audit.md).",
            "",
            f"Defined: {len(specification_ids)}. Backend-tagged: {len(specification_ids & tested_ids)}. Without a backend tag: {len(missing)}.",
            "",
            "| Requirement | Functionality | Specification | Evidence Status | Test Files |",
            "| --- | --- | --- | --- | --- |",
            *rows,
            "",
        ]
        args.markdown_output.parent.mkdir(parents=True, exist_ok=True)
        args.markdown_output.write_text("\n".join(text), encoding="utf-8")
        print(f"Inventory written: {args.markdown_output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())