from __future__ import annotations

from pathlib import Path
from typing import Any


class GitError(RuntimeError):
    pass


class Repo:
    def __init__(self, top: Path, objects: Path, index: Path) -> None:
        self.top = top
        self.objects = objects
        self.index = index


def _resolve_git_path(top: Path, value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else (top / path).resolve()


def parse_unified(text: str) -> list[dict[str, Any]]:
    """
    Hunks of a unified diff: ``{old_start, new_start, header, lines: [{kind, old, new, text}]}``;
    ``kind`` is ctx/add/del.
    """
    hunks: list[dict[str, Any]] = []
    hunk: dict[str, Any] | None = None
    old = new = 0
    rows = text.split("\n")
    if rows and rows[-1] == "":
        rows.pop()
    for line in rows:
        if line.startswith("@@"):
            try:
                ranges = line.split("@@")[1].strip().split(" ")
                old = int(ranges[0].lstrip("-").split(",")[0])
                new = int(ranges[1].lstrip("+").split(",")[0])
            except (IndexError, ValueError):
                old = new = 0
            hunk = {"old_start": old, "new_start": new, "header": line, "lines": []}
            hunks.append(hunk)
            continue
        if hunk is None:
            continue
        if line.startswith("\\"):
            if hunk["lines"]:
                hunk["lines"][-1]["no_newline"] = True
            continue
        if line.startswith("+"):
            hunk["lines"].append({"kind": "add", "old": None, "new": new, "text": line[1:]})
            new += 1
        elif line.startswith("-"):
            hunk["lines"].append({"kind": "del", "old": old, "new": None, "text": line[1:]})
            old += 1
        elif line.startswith(" "):
            hunk["lines"].append({"kind": "ctx", "old": old, "new": new, "text": line[1:]})
            old += 1
            new += 1
    return hunks
