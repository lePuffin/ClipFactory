#!/usr/bin/env python3
"""Validate local Markdown links and requirement traceability references."""

from __future__ import annotations

import re
import sys
from pathlib import Path
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[1]
LINK = re.compile(r"(?<!!)\[[^\]]*\]\(([^)]+)\)")
REQ_HEADING = re.compile(r"^### (CF-(?:REQ|NFR)-\d{3})\s+[—-]", re.MULTILINE)
REQ_REFERENCE = re.compile(r"\bCF-(?:REQ|NFR)-\d{3}\b")


def _anchor(text: str) -> str:
    text = re.sub(r"[`*_~]", "", text).lower()
    text = re.sub(r"\s", "-", text.strip())
    return re.sub(r"[^\w-]", "", text)


def _markdown_files() -> list[Path]:
    roots = [ROOT / "doc", ROOT / ".github"]
    files = [ROOT / name for name in ("README.md", "AGENTS.md") if (ROOT / name).exists()]
    for directory in roots:
        if directory.exists():
            files.extend(directory.rglob("*.md"))
    return sorted(set(files))


def check_links(files: list[Path]) -> list[str]:
    problems: list[str] = []
    for markdown in files:
        content = markdown.read_text(encoding="utf-8")
        for raw_target in LINK.findall(content):
            target = raw_target.strip().split()[0].strip("<>")
            if not target or target.startswith(("http://", "https://", "mailto:", "#")):
                continue
            path_text, _, fragment = target.partition("#")
            resolved = (markdown.parent / unquote(path_text)).resolve()
            if not resolved.exists():
                problems.append(f"{markdown.relative_to(ROOT)}: missing link target {path_text}")
                continue
            if fragment and resolved.suffix.lower() == ".md":
                headings = [_anchor(match.group(1)) for match in re.finditer(r"^#{1,6}\s+(.+?)\s*#*\s*$", resolved.read_text(encoding="utf-8"), re.MULTILINE)]
                if unquote(fragment).lower() not in headings:
                    problems.append(f"{markdown.relative_to(ROOT)}: missing anchor #{fragment} in {path_text}")
    return problems


def check_requirement_traceability(files: list[Path]) -> list[str]:
    definitions: list[tuple[str, Path]] = []
    for markdown in files:
        if markdown.name == "traceability.md":
            continue
        definitions.extend((identifier, markdown) for identifier in REQ_HEADING.findall(markdown.read_text(encoding="utf-8")))
    counts: dict[str, int] = {}
    for identifier, _ in definitions:
        counts[identifier] = counts.get(identifier, 0) + 1
    problems = [f"{identifier} is defined {count} times" for identifier, count in counts.items() if count != 1]
    traceability = ROOT / "doc/specifications/traceability.md"
    if traceability.exists():
        matrix = traceability.read_text(encoding="utf-8")
        problems.extend(f"{identifier} is missing from traceability.md" for identifier in counts if identifier not in matrix)
    return problems


def main() -> int:
    files = _markdown_files()
    problems = check_links(files) + check_requirement_traceability(files)
    if problems:
        print("Documentation checks failed:")
        print("\n".join(f"- {problem}" for problem in problems))
        return 1
    print(f"Documentation checks passed ({len(files)} Markdown files).")
    return 0


if __name__ == "__main__":
    sys.exit(main())