"""
Gateway settings file: defaults, validation and atomic persistence.

| name                  | contract                                                                    |
|-----------------------|-----------------------------------------------------------------------------|
| ``normalize()``       | a complete, validated settings object; unknown fields dropped               |
| ``SettingsStore``     | settings bound to one file; reads fall back to the defaults, writes are atomic (0600) |
| ``is_model_id()``     | ``provider:model`` shape check shared with the key allowlists               |

Settings object: ``enabled``, ``host``, ``port``, ``aliases`` (request model name → gateway model id) and ``pricing``
(gateway model id → ``{input, output}`` price per one million tokens).
"""

from __future__ import annotations

import copy
import json
import math
import os
import re
from pathlib import Path
from typing import Any

from pyharness import package_toml

_CFG = package_toml(__file__)["settings"]
DEFAULT_HOST: str = _CFG["DEFAULT_HOST"]
DEFAULT_PORT: int = _CFG["DEFAULT_PORT"]
MAX_ENTRIES: int = _CFG["MAX_ENTRIES"]
MODEL_ID = re.compile(r"^[^\s:]{1,100}:\S{1,200}$")
HOST_FORBIDDEN = re.compile(r"[\s/\\]")


class SettingsError(ValueError):
    """Invalid settings; ``field`` names the offending top-level field."""

    def __init__(self, field: str, message: str) -> None:
        super().__init__(message)
        self.field = field


def is_model_id(value: Any) -> bool:
    return isinstance(value, str) and MODEL_ID.match(value) is not None


def _host(value: Any) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 253 or HOST_FORBIDDEN.search(value.strip()):
        raise SettingsError("host", "host must be a hostname or IP address")
    return value.strip()


def _port(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 65535:
        raise SettingsError("port", "port must be an integer from 1 to 65535")
    return value


def _table(value: Any, field: str, noun: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise SettingsError(field, f"{field} must be an object")
    if len(value) > MAX_ENTRIES:
        raise SettingsError(field, f"at most {MAX_ENTRIES} {noun}")
    return value


def _aliases(value: Any) -> dict[str, str]:
    out: dict[str, str] = {}
    for alias, target in _table(value, "aliases", "aliases").items():
        if not alias.strip() or len(alias) > 200 or re.search(r"\s", alias):
            raise SettingsError("aliases", f'invalid alias "{alias}"')
        if not is_model_id(target):
            raise SettingsError("aliases", f'alias "{alias}" must point to a provider:model id')
        out[alias] = target
    return out


def _pricing(value: Any) -> dict[str, dict[str, float]]:
    out: dict[str, dict[str, float]] = {}
    for model_id, raw in _table(value, "pricing", "prices").items():
        if not is_model_id(model_id):
            raise SettingsError("pricing", f'"{model_id}" is not a provider:model id')
        price = raw if isinstance(raw, dict) else {}
        row: dict[str, float] = {}
        for name in ("input", "output"):
            amount = price.get(name)
            if (
                isinstance(amount, bool)
                or not isinstance(amount, int | float)
                or not math.isfinite(amount)
                or amount < 0
            ):
                raise SettingsError("pricing", f"{model_id}: {name} price must be a non-negative number")
            row[name] = amount
        out[model_id] = row
    return out


def normalize(raw: Any, defaults: dict[str, Any] | None = None) -> dict[str, Any]:
    """Validate a complete settings object; ``defaults`` supplies ``enabled``, ``host`` and ``port`` when absent."""
    data = raw if isinstance(raw, dict) else {}
    defaults = defaults or {}
    enabled = data.get("enabled", defaults.get("enabled", True))
    if not isinstance(enabled, bool):
        raise SettingsError("enabled", "enabled must be a boolean")
    return {
        "enabled": enabled,
        "host": _host(data.get("host", defaults.get("host", DEFAULT_HOST))),
        "port": _port(data.get("port", defaults.get("port", DEFAULT_PORT))),
        "aliases": _aliases(data.get("aliases")),
        "pricing": _pricing(data.get("pricing")),
    }


def write_private(path: Path, data: Any) -> None:
    """Write ``data`` as JSON through a temporary file with mode 0600."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.tmp-{os.getpid()}")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.chmod(0o600)
    tmp.replace(path)


class SettingsStore:
    """Settings bound to one file."""

    def __init__(self, path: Path, defaults: dict[str, Any] | None = None) -> None:
        self.path = path
        self.defaults = defaults or {}
        self._current = self._read()

    def _read(self) -> dict[str, Any]:
        try:
            return normalize(json.loads(self.path.read_text(encoding="utf-8")), self.defaults)
        except (OSError, ValueError):
            return normalize({}, self.defaults)

    def get(self) -> dict[str, Any]:
        return copy.deepcopy(self._current)

    def save(self, raw: Any) -> dict[str, Any]:
        """Validate and persist ``raw``; raises :class:`SettingsError`."""
        settings = normalize(raw, self.defaults)
        write_private(self.path, settings)
        self._current = settings
        return self.get()
