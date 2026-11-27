from __future__ import annotations

import json
import math
import re
from collections.abc import Mapping, Sequence
from typing import Any

from pyxis_harness import package_toml

from .protocol import HEADER_NAME, VARIABLE_NAME

_CFG = package_toml(__file__)["capture"]
MAX_CAPTURED_LENGTH: int = _CFG["MAX_CAPTURED_LENGTH"]
MAX_PATH_LENGTH: int = _CFG["MAX_PATH_LENGTH"]

QUOTED = re.compile(r"([\"'])(.*)\1")
INDEX = re.compile(r"[0-9]+")
NAME = re.compile(r"[^.\[\]]+")
SECONDS = re.compile(r"[0-9]+(\.[0-9]+)?")
LINE_BREAK = re.compile(r"[\r\n]")
# Largest magnitude JSON prints an integral float without an exponent.
PLAIN_FLOAT = 1e21


def parse_json_path(path: str) -> list[str | int]:
    """
    Segments of a JSON path: ``data.token``, ``items[0].id``, ``$.a["b.c"]``. A leading ``$`` is optional; names
    follow dots, indexes and quoted names sit in brackets. Raises ``ValueError`` on a malformed path.
    """
    text = path.strip()
    if text in ("", "$"):
        raise ValueError("path is empty")
    if len(text) > MAX_PATH_LENGTH:
        raise ValueError("path is too long")
    out: list[str | int] = []
    i = 1 if text.startswith("$") else 0
    first = i == 0
    while i < len(text):
        char = text[i]
        if char == "[":
            close = text.find("]", i)
            if close < 0:
                raise ValueError(f'unclosed "[" at {i}')
            inner = text[i + 1 : close].strip()
            quoted = QUOTED.fullmatch(inner)
            if quoted is not None:
                out.append(quoted.group(2))
            elif INDEX.fullmatch(inner):
                out.append(int(inner))
            else:
                raise ValueError(f'invalid index "{inner}"')
            i = close + 1
        else:
            if char == ".":
                i += 1
            elif not first:
                raise ValueError(f'unexpected "{char}" at {i}')
            match = NAME.match(text, i)
            if match is None:
                raise ValueError(f"name expected at {i}")
            out.append(match.group(0))
            i = match.end()
        first = False
    return out


def read_path(root: Any, segments: Sequence[str | int]) -> Any:
    """Value at a parsed path; ``None`` when a step is missing."""
    node = root
    for segment in segments:
        if isinstance(node, list):
            index = segment if isinstance(segment, int) else int(segment) if INDEX.fullmatch(segment) else -1
            node = node[index] if 0 <= index < len(node) else None
        elif isinstance(node, dict):
            node = node.get(str(segment))
        else:
            return None
    return node


def _not_json(constant: str) -> Any:
    raise ValueError(constant)


def _scalar_text(value: Any) -> str | None:
    """A string, number or boolean as the text JSON writes for it; ``None`` for every other value."""
    if isinstance(value, str):
        return value
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return str(int(value)) if value.is_integer() and abs(value) < PLAIN_FLOAT else repr(value)
    return None


def _lifetime_ms(seconds: Any) -> int | None:
    """Milliseconds of a positive number of seconds, given as a number or as digits; ``None`` otherwise."""
    if isinstance(seconds, str) and SECONDS.fullmatch(seconds.strip()):
        seconds = float(seconds)
    if isinstance(seconds, bool) or not isinstance(seconds, int | float):
        return None
    try:
        ms = float(seconds) * 1000
    except OverflowError:
        return None
    return int(ms + 0.5) if math.isfinite(ms) and ms > 0 else None


def run_captures(
    rules: Sequence[Mapping[str, Any]], status: int, headers: Mapping[str, str], body: str, truncated: bool
) -> tuple[dict[str, str], dict[str, int], list[dict[str, Any]]]:
    """
    Run capture rules on a response as received: ``headers`` looks names up without regard to case, ``body`` is the
    decoded body (empty for a binary one), ``truncated`` tells that the body cap cut it short.

    Returns the captured values by variable name, their lifetimes in ms by variable name, and one result per rule
    run. Rules switched off or without a name are left out; a status outside 2xx captures nothing. A lifetime comes
    from ``ttlPath`` (seconds, read from the JSON body), else from ``ttlSeconds``; a lifetime path that yields no
    positive number leaves the value without expiry and puts a warning on the result.
    """
    values: dict[str, str] = {}
    lifetimes: dict[str, int] = {}
    results: list[dict[str, Any]] = []
    parsed: list[tuple[Any, str | None]] = []

    def document() -> tuple[Any, str | None]:
        """The JSON body and why it cannot be read, parsed once."""
        if not parsed:
            if truncated:
                parsed.append((None, "response body is truncated"))
            else:
                try:
                    parsed.append((json.loads(body, parse_constant=_not_json), None))
                except ValueError:
                    parsed.append((None, "response body is not JSON"))
        return parsed[0]

    def read(rule: Mapping[str, Any]) -> tuple[Any, str | None]:
        """The value a rule addresses, or why there is none."""
        if rule["source"] == "header":
            header = rule["path"].strip()
            if not header:
                return None, "header name is empty"
            if not HEADER_NAME.match(header):
                return None, f'invalid header name "{header}"'
            found = headers.get(header)
            return (found, None) if found is not None else (None, f'header "{header}" not found')
        try:
            segments = parse_json_path(rule["path"])
        except ValueError as exc:
            return None, str(exc)
        root, error = document()
        if error is not None:
            return None, error
        found = read_path(root, segments)
        return (found, None) if found is not None else (None, f'path "{rule["path"].strip()}" not found')

    def check(found: Any) -> tuple[str, str | None]:
        """The text stored for a value read, or why it is not stored."""
        text = _scalar_text(found)
        if text is None:
            return "", "value is not a string, number or boolean"
        if not text:
            return "", "value is empty"
        if len(text) > MAX_CAPTURED_LENGTH:
            return "", "value is too long"
        if LINE_BREAK.search(text):
            return "", "value contains line breaks"
        return text, None

    def capture(rule: Mapping[str, Any], name: str) -> tuple[str, str | None]:
        if not VARIABLE_NAME.match(name):
            return "", "invalid variable name"
        if not 200 <= status <= 299:
            return "", f"response status {status}"
        found, error = read(rule)
        return ("", error) if error is not None else check(found)

    for rule in rules:
        name = rule["name"].strip()
        if not rule["enabled"] or not name:
            continue
        value, error = capture(rule, name)
        if error is not None:
            results.append({"name": name, "ok": False, "error": error})
            continue
        values[name] = value
        lifetimes.pop(name, None)
        result: dict[str, Any] = {"name": name, "ok": True}
        ttl_path = rule["ttlPath"].strip()
        if ttl_path:
            root, unreadable = document()
            try:
                lifetime = None if unreadable else _lifetime_ms(read_path(root, parse_json_path(ttl_path)))
            except ValueError:
                lifetime = None
            if lifetime is None:
                result["warning"] = f'lifetime "{ttl_path}" is not a positive number of seconds'
            else:
                lifetimes[name] = lifetime
        elif rule["ttlSeconds"] > 0:
            lifetimes[name] = rule["ttlSeconds"] * 1000
        results.append(result)
    return values, lifetimes, results
