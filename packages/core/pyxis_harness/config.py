from __future__ import annotations

import copy
import os
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError


class ConfigError(ValueError):
    """Invalid configuration, patch, or interpolation."""


class Entry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    name: str | None = None
    config: dict[str, Any] | None = None
    disabled: bool = False
    isolate: list[str] = Field(default_factory=list)
    children: list[Entry] | None = None
    source: str | None = Field(default=None, description="layer that inserted this entry")

    @property
    def is_group(self) -> bool:
        return self.children is not None


class PatchOp(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    name: str | None = None
    config: dict[str, Any] | None = None
    merge: bool = False
    disabled: bool | None = None
    isolate: list[str] | None = None
    children: list[dict[str, Any]] | None = None
    remove: bool = False
    parent: str | None = None
    before: str | None = None
    after: str | None = None


Tree = list[Entry]


# ---------------------------------------------------------------------- YAML IO
def load_yaml(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    text = path.read_text(encoding="utf-8")
    data = yaml.safe_load(text)
    return default if data is None else data


def dump_yaml(data: Any) -> str:
    return yaml.safe_dump(data, sort_keys=False, allow_unicode=True, default_flow_style=False)


def write_yaml(path: Path, data: Any, header: str | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    body = dump_yaml(data)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text((header or "") + body, encoding="utf-8")
    tmp.replace(path)


def parse_ops(raw: Any, source: str) -> list[PatchOp]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ConfigError(f"{source}: a patch must be a YAML list of operations, got {type(raw).__name__}")
    ops = []
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            raise ConfigError(f"{source}[{index}]: each operation must be a mapping")
        try:
            ops.append(PatchOp.model_validate(item))
        except ValidationError as exc:
            raise ConfigError(f"{source}[{index}] ({item.get('id', '?')}): {exc}") from None
    return ops


# ---------------------------------------------------------------------- tree helpers
def iter_entries(tree: Tree, parents: tuple[Entry, ...] = ()) -> Iterable[tuple[Entry, tuple[Entry, ...]]]:
    for entry in tree:
        yield entry, parents
        if entry.children is not None:
            yield from iter_entries(entry.children, (*parents, entry))


def find(tree: Tree, entry_id: str) -> tuple[Tree, int] | None:
    for index, entry in enumerate(tree):
        if entry.id == entry_id:
            return tree, index
        if entry.children is not None:
            hit = find(entry.children, entry_id)
            if hit is not None:
                return hit
    return None


def _entry_from_mapping(raw: dict[str, Any], source: str) -> Entry:
    data = {k: v for k, v in raw.items() if k not in {"merge", "remove", "parent", "before", "after"}}
    children = data.pop("children", None)
    entry = Entry.model_validate({**data, "source": source})
    if children is not None:
        entry.children = [_entry_from_mapping(child, source) for child in children]
    return entry


def deep_merge(base: dict[str, Any], extra: dict[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(base)
    for key, value in extra.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = deep_merge(out[key], value)
        else:
            out[key] = copy.deepcopy(value)
    return out


def apply_patch(tree: Tree, ops: list[PatchOp], source: str) -> list[str]:
    """Apply ``ops`` to ``tree`` in place; returns warnings."""
    warnings: list[str] = []
    for op in ops:
        hit = find(tree, op.id)
        if op.remove:
            if hit is None:
                warnings.append(f"{source}: remove target {op.id!r} not found")
            else:
                container, index = hit
                del container[index]
            continue
        if hit is not None:
            container, index = hit
            entry = container[index]
            if op.name is not None:
                entry.name = op.name
            if op.config is not None:
                entry.config = deep_merge(entry.config or {}, op.config) if op.merge else copy.deepcopy(op.config)
            if op.disabled is not None:
                entry.disabled = op.disabled
            if op.isolate is not None:
                entry.isolate = list(op.isolate)
            if op.children is not None:
                entry.children = [_entry_from_mapping(child, source) for child in op.children]
            if op.parent or op.before or op.after:
                warnings.append(f"{source}: position fields on existing entry {op.id!r} are ignored")
            continue
        if op.name is None and op.children is None:
            warnings.append(f"{source}: {op.id!r} does not exist and the op has no `name`/`children`; skipped")
            continue
        entry = _entry_from_mapping(op.model_dump(exclude_none=True, exclude_defaults=False), source)
        if op.disabled is None:
            entry.disabled = False
        _insert(tree, entry, op, source, warnings)
    return warnings


def _insert(tree: Tree, entry: Entry, op: PatchOp, source: str, warnings: list[str]) -> None:
    if op.before or op.after:
        anchor = op.before or op.after
        hit = find(tree, anchor)  # type: ignore[arg-type]
        if hit is None:
            warnings.append(f"{source}: anchor {anchor!r} for {entry.id!r} not found; appended instead")
        else:
            container, index = hit
            container.insert(index if op.before else index + 1, entry)
            return
    if op.parent:
        hit = find(tree, op.parent)
        if hit is None or tree is None:
            warnings.append(f"{source}: parent {op.parent!r} for {entry.id!r} not found; appended to root")
        else:
            container, index = hit
            group = container[index]
            if group.children is None:
                warnings.append(f"{source}: parent {op.parent!r} is not a group; appended to root")
            else:
                group.children.append(entry)
                return
    tree.append(entry)


def validate_tree(tree: Tree) -> None:
    seen: dict[str, str | None] = {}
    for entry, _ in iter_entries(tree):
        if entry.id in seen:
            raise ConfigError(f"duplicate entry id {entry.id!r} (from {seen[entry.id]} and {entry.source})")
        seen[entry.id] = entry.source
        if entry.children is None and not entry.name:
            raise ConfigError(f"entry {entry.id!r} has neither `name` nor `children`")


def compose(layers: list[tuple[str, list[PatchOp]]]) -> tuple[Tree, list[str]]:
    tree: Tree = []
    warnings: list[str] = []
    for source, ops in layers:
        warnings.extend(apply_patch(tree, ops, source))
    validate_tree(tree)
    return tree, warnings


def tree_to_data(tree: Tree, with_source: bool = False) -> list[dict[str, Any]]:
    out = []
    for entry in tree:
        data: dict[str, Any] = {"id": entry.id}
        if entry.name:
            data["name"] = entry.name
        if entry.disabled:
            data["disabled"] = True
        if entry.isolate:
            data["isolate"] = list(entry.isolate)
        if entry.config:
            data["config"] = entry.config
        if entry.children is not None:
            data["children"] = tree_to_data(entry.children, with_source)
        if with_source and entry.source:
            data["source"] = entry.source
        out.append(data)
    return out


# ---------------------------------------------------------------------- interpolation
def interpolate(value: Any, variables: dict[str, str]) -> Any:
    """
    Resolve placeholders in strings, recursively through dicts and lists.

    | placeholder              | value                                                 |
    |--------------------------|-------------------------------------------------------|
    | ``${env:NAME}``          | environment variable; unset → ``""``                  |
    | ``${env:NAME:-default}`` | environment variable, else ``default``; defaults nest |
    | ``${var}``               | entry of ``variables``                                |
    | ``${credential:REF}``    | kept as written                                       |

    - Substituted text is literal and never re-scanned.
    - A string that is exactly one unset ``${env:NAME}`` becomes ``None``.
    - The plugin that reads a value resolves ``${credential:REF}`` at runtime through the profile credential store.
    """
    if isinstance(value, dict):
        return {k: interpolate(v, variables) for k, v in value.items()}
    if isinstance(value, list):
        return [interpolate(v, variables) for v in value]
    if not isinstance(value, str) or "${" not in value:
        return value
    return _interpolate_str(value, variables, allow_none=True)


def _matching_brace(text: str, start: int) -> int:
    """Index of the ``}`` closing the ``${`` that starts at ``start``."""
    depth = 0
    i = start
    while i < len(text):
        if text.startswith("${", i):
            depth += 1
            i += 2
            continue
        if text[i] == "}":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    raise ConfigError(f"unterminated ${{...}} in {text!r}")


def _interpolate_str(text: str, variables: dict[str, str], *, allow_none: bool = False) -> str | None:
    pieces: list[str] = []
    i = 0
    while i < len(text):
        j = text.find("${", i)
        if j < 0:
            pieces.append(text[i:])
            break
        pieces.append(text[i:j])
        k = _matching_brace(text, j)
        token = text[j + 2 : k]
        resolved = text[j : k + 1] if token.startswith("credential:") else _resolve_token(token, variables)
        if resolved is None:
            if allow_none and j == 0 and k == len(text) - 1:
                return None
            resolved = ""
        pieces.append(resolved)
        i = k + 1
    return "".join(pieces)


def _resolve_token(token: str, variables: dict[str, str]) -> str | None:
    token = token.strip()
    if token.startswith("env:"):
        name, sep, default = token[4:].partition(":-")
        got = os.environ.get(name)
        if got not in (None, ""):
            return got
        return _interpolate_str(default, variables) if sep else None
    if token in variables:
        return variables[token]
    raise ConfigError(f"unknown variable ${{{token}}} (known: env:*, {', '.join(sorted(variables))})")
