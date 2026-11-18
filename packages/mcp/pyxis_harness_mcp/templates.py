from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from urllib.parse import quote

from pyxis_harness.credentials import REFERENCE

from .config import ServerConfig

TEMPLATE = re.compile(rf"\$\{{credential:({REFERENCE.pattern.strip('^$')})\}}")
REDACTED = "[redacted]"
REDACT_MIN_LENGTH = 3


def has_template(value: str) -> bool:
    """Whether ``value`` contains a credential template."""
    return TEMPLATE.search(value) is not None


def _strings(cfg: ServerConfig) -> list[str]:
    return [cfg.command or "", *cfg.args, *cfg.env.values(), cfg.cwd or "", cfg.url or "", *cfg.headers.values()]


def references(cfg: ServerConfig) -> list[str]:
    """Credential references in the transport strings of ``cfg``: unique, in order of first appearance."""
    return list(dict.fromkeys(ref for text in _strings(cfg) for ref in TEMPLATE.findall(text)))


def expand(cfg: ServerConfig, lookup: Callable[[str], str | None]) -> tuple[ServerConfig, list[str], list[str]]:
    """
    Resolve the templates of ``cfg`` through ``lookup(reference)``.

    Returns the expanded configuration, the resolved values, and the references ``lookup`` has no value for. A
    template of a missing reference stays as written.
    """
    found = {ref: lookup(ref) for ref in references(cfg)}

    def fill(text: str) -> str:
        return TEMPLATE.sub(lambda match: found[match[1]] or match[0], text)

    expanded = cfg.model_copy(
        update={
            "command": fill(cfg.command) if cfg.command is not None else None,
            "args": [fill(arg) for arg in cfg.args],
            "env": {key: fill(value) for key, value in cfg.env.items()},
            "cwd": fill(cfg.cwd) if cfg.cwd is not None else None,
            "url": fill(cfg.url) if cfg.url is not None else None,
            "headers": {key: fill(value) for key, value in cfg.headers.items()},
        }
    )
    return expanded, [value for value in found.values() if value], [ref for ref, value in found.items() if not value]


def redact(text: str, values: Iterable[str]) -> str:
    """
    ``text`` with each value of three characters or more, and its URL-encoded form, replaced by ``[redacted]``.

    Where several values match at one position, the longest is replaced.
    """
    secrets = {form for value in values if len(value) >= REDACT_MIN_LENGTH for form in (value, quote(value, safe=""))}
    if not secrets:
        return text
    pattern = "|".join(re.escape(secret) for secret in sorted(secrets, key=lambda secret: (-len(secret), secret)))
    return re.sub(pattern, REDACTED, text)
