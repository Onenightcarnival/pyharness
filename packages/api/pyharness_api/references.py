"""
``@path`` references in a user message: the referenced files and directories travel with the prompt.

A token ``@path`` or ``@"path with spaces"`` at the start of the text or after whitespace or a bracket names a
file or directory of the session's workspace (``/`` or relative to its root). Resolvable references are appended to
the message as ``<attached-file path=...>`` blocks (text, clipped) or ``<attached-directory path=...>`` listings;
the ``@path`` text itself stays in place. Tokens that resolve to nothing (an email address, a handle) are left alone.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

from pyharness import package_toml

TOKEN = re.compile(r'(?:(?<=\s)|(?<=[(\[{,，、])|^)@(?:"(?P<quoted>[^"\n]+)"|(?P<bare>[^\s"@,;:!?)\]}]+))')
SKIP_DIRS: set[str] = set(package_toml(__file__)["references"]["SKIP_DIRS"])  # left out of listings and search
FILE_CHARS = 60_000
TOTAL_CHARS = 240_000
DIR_ENTRIES = 200


def tokens(text: str) -> list[tuple[str, str]]:
    """``(token, path)`` pairs in order of appearance, deduplicated by path."""
    seen: set[str] = set()
    out = []
    for m in TOKEN.finditer(text):
        path = (m.group("quoted") or m.group("bare") or "").rstrip(".")
        if not path or path in seen:
            continue
        seen.add(path)
        out.append((m.group(0), path))
    return out


def _read_text(real: Path, limit: int) -> tuple[str, bool, bool]:
    """``(text, truncated, binary)``."""
    data = real.read_bytes()[: limit * 4]
    if b"\0" in data[:8192]:
        return "", False, True
    text = data.decode("utf-8", errors="replace")
    return text[:limit], len(text) > limit or real.stat().st_size > limit * 4, False


def expand(text: str, workspace: Any) -> tuple[str, list[dict[str, Any]]]:
    """``(content, references)``: the text with attachment blocks appended for every reference that resolves."""
    blocks: list[str] = []
    refs: list[dict[str, Any]] = []
    budget = TOTAL_CHARS
    for token, path in tokens(text):
        try:
            real = workspace.resolve(path)
        except ValueError:
            continue
        if not real.exists():
            continue
        virtual = "/" + real.relative_to(workspace.root).as_posix() if real != workspace.root else "/"
        if real.is_dir():
            names = []
            try:
                for item in sorted(real.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())):
                    if item.name in SKIP_DIRS:
                        continue
                    names.append(item.name + ("/" if item.is_dir() else ""))
            except OSError:
                continue
            listing = "\n".join(names[:DIR_ENTRIES]) + (
                f"\n… ({len(names) - DIR_ENTRIES} more)" if len(names) > DIR_ENTRIES else ""
            )
            blocks.append(f'<attached-directory path="{virtual}">\n{listing}\n</attached-directory>')
            refs.append({"token": token, "path": virtual, "kind": "directory", "entries": len(names)})
            continue
        if not real.is_file():
            continue
        try:
            body, truncated, binary = _read_text(real, min(FILE_CHARS, max(budget, 0)))
        except OSError:
            continue
        if binary:
            blocks.append(
                f'<attached-file path="{virtual}" binary="true" bytes="{real.stat().st_size}"></attached-file>'
            )
            refs.append({"token": token, "path": virtual, "kind": "binary"})
            continue
        budget -= len(body)
        note = ' truncated="true"' if truncated or budget < 0 else ""
        blocks.append(f'<attached-file path="{virtual}"{note}>\n{body}\n</attached-file>')
        refs.append(
            {
                "token": token,
                "path": virtual,
                "kind": "file",
                "chars": len(body),
                "truncated": bool(truncated or budget < 0),
            }
        )
        if budget <= 0:
            break
    if not blocks:
        return text, []
    return text.rstrip() + "\n\n" + "\n\n".join(blocks), refs


def search(
    root: Path, query: str, limit: int = 50, max_visited: int = 30_000, *, hidden: bool = False, fuzzy: bool = True
) -> list[dict[str, Any]]:
    """
    Files and directories under ``root`` whose virtual path matches ``query`` (substring, then subsequence),
    ranked.

    | argument   | effect                                                                         |
    |------------|--------------------------------------------------------------------------------|
    | ``hidden`` | dot-files and dot-directories take part; ``SKIP_DIRS`` stay out in either case |
    | ``fuzzy``  | ``False`` drops the subsequence matches                                        |
    """
    q = query.strip().lower().lstrip("/")
    results: list[tuple[int, str, dict[str, Any]]] = []
    visited = 0
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS and (hidden or not d.startswith(".")))
        rel = Path(dirpath).relative_to(root).as_posix()
        prefix = "" if rel == "." else rel + "/"
        files = [(f, False) for f in filenames if hidden or not f.startswith(".")]
        for name, is_dir in [(d, True) for d in dirnames] + files:
            visited += 1
            virtual = prefix + name + ("/" if is_dir else "")
            score = _score(virtual.lower(), name.lower(), q, fuzzy)
            if score is not None:
                results.append((score, virtual, {"path": "/" + virtual, "name": name, "dir": is_dir}))
            if visited >= max_visited:
                break
        if visited >= max_visited:
            break
    results.sort(key=lambda r: (r[0], len(r[1]), r[1]))
    return [r[2] for r in results[:limit]]


def _score(path: str, name: str, q: str, fuzzy: bool = True) -> int | None:
    if not q:
        return 2 if "/" in path.rstrip("/") else 0
    if name.startswith(q):
        return 0
    if q in name:
        return 1
    if q in path:
        return 2
    if not fuzzy:
        return None
    i = 0
    for ch in path:
        if ch == q[i]:
            i += 1
            if i == len(q):
                return 3
    return None


ATTACHMENT = re.compile(r"\n*<attached-(?:file|directory)\b[^>]*>.*?</attached-(?:file|directory)>", re.DOTALL)


def strip_attachments(text: str) -> str:
    return ATTACHMENT.sub("", text or "").rstrip()


__all__ = ["expand", "search", "strip_attachments", "tokens"]
