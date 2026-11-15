"""
API keys of the gateway: a 0600 JSON file holding every key in full, so the page can show and copy them.

| name               | contract                                                                         |
|--------------------|----------------------------------------------------------------------------------|
| ``KeyStore``       | keys bound to one file; every mutation rewrites the file atomically              |
| ``verify()``       | constant-time match of a presented key against every enabled key                 |
| ``touch()``        | records ``lastUsedAt``; at most one write per minute per key                     |
| ``presented_key()``| the key of a request: ``Authorization: Bearer <key>`` or ``x-api-key: <key>``    |

A key view: ``id``, ``name``, ``prefix``, ``enabled``, ``models`` (allowed gateway model ids; ``None`` allows every
model), ``createdAt``, ``lastUsedAt`` (epoch milliseconds).
"""

from __future__ import annotations

import hmac
import json
import re
import secrets
import time
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from pyharness import package_toml

from .settings import is_model_id, write_private

_CFG = package_toml(__file__)["keys"]
KEY_PREFIX: str = _CFG["KEY_PREFIX"]
MAX_KEYS: int = _CFG["MAX_KEYS"]
MAX_NAME: int = _CFG["MAX_NAME"]
MAX_MODELS: int = _CFG["MAX_MODELS"]
TOUCH_INTERVAL_MS: int = _CFG["TOUCH_INTERVAL_MS"]
PREFIX_CHARS = len(KEY_PREFIX) + 8
BEARER = re.compile(r"^\s*Bearer\s+(\S+)\s*$", re.IGNORECASE)


class KeyStoreError(ValueError):
    """Key operation failure; ``code`` is ``invalid``, ``limit`` or ``missing``."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def now_ms() -> int:
    return int(time.time() * 1000)


def generate_key() -> str:
    return KEY_PREFIX + secrets.token_hex(24)


def _view(record: dict[str, Any]) -> dict[str, Any]:
    view = {k: v for k, v in record.items() if k != "key"}
    view["models"] = None if record["models"] is None else list(record["models"])
    return view


def _name(value: Any) -> str:
    if not isinstance(value, str):
        raise KeyStoreError("invalid", "name must be a string")
    name = value.strip()
    if not name or len(name) > MAX_NAME:
        raise KeyStoreError("invalid", f"name must be 1–{MAX_NAME} characters")
    return name


def _models(value: Any) -> list[str] | None:
    if value is None:
        return None
    if not isinstance(value, list) or len(value) > MAX_MODELS:
        raise KeyStoreError("invalid", "models must be a list of provider:model ids")
    models: list[str] = []
    for model_id in value:
        if not is_model_id(model_id):
            raise KeyStoreError("invalid", f'"{model_id}" is not a provider:model id')
        if model_id not in models:
            models.append(model_id)
    return models or None


def _load(path: Path) -> list[dict[str, Any]]:
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    entries = parsed if isinstance(parsed, list) else parsed.get("keys") if isinstance(parsed, dict) else None
    records = []
    for entry in entries if isinstance(entries, list) else []:
        if not isinstance(entry, dict) or not isinstance(entry.get("id"), str) or not isinstance(entry.get("key"), str):
            continue
        models = (
            [m for m in entry.get("models") or [] if is_model_id(m)] if isinstance(entry.get("models"), list) else []
        )
        created, used = entry.get("createdAt"), entry.get("lastUsedAt")
        records.append(
            {
                "id": entry["id"],
                "name": entry["name"] if isinstance(entry.get("name"), str) else entry["id"],
                "key": entry["key"],
                "prefix": entry["key"][:PREFIX_CHARS],
                "enabled": entry.get("enabled") is not False,
                "models": models or None,
                "createdAt": created if isinstance(created, int) else 0,
                "lastUsedAt": used if isinstance(used, int) else None,
            }
        )
    return records


class KeyStore:
    """Keys bound to one file."""

    def __init__(self, path: Path, now: Callable[[], int] = now_ms) -> None:
        self.path = path
        self._now = now
        self._keys = _load(path)

    def _persist(self) -> None:
        write_private(self.path, {"keys": self._keys})

    def _record(self, key_id: str) -> dict[str, Any]:
        record = next((entry for entry in self._keys if entry["id"] == key_id), None)
        if record is None:
            raise KeyStoreError("missing", "key not found")
        return record

    def list(self) -> list[dict[str, Any]]:
        return [_view(record) for record in self._keys]

    def reveal(self, key_id: str) -> str | None:
        """The complete key of one record, for the page's show and copy actions."""
        return next((entry["key"] for entry in self._keys if entry["id"] == key_id), None)

    def ensure_one(self, name: str) -> dict[str, Any] | None:
        """Create the first key when none exists; ``None`` when keys already exist."""
        return None if self._keys else self.create(name, None)

    def create(self, name: Any, models: Any) -> dict[str, Any]:
        """``{"key", "record"}`` of a new key; raises :class:`KeyStoreError`."""
        if len(self._keys) >= MAX_KEYS:
            raise KeyStoreError("limit", f"at most {MAX_KEYS} keys")
        key = generate_key()
        record = {
            "id": secrets.token_hex(6),
            "name": _name(name),
            "key": key,
            "prefix": key[:PREFIX_CHARS],
            "enabled": True,
            "models": _models(models),
            "createdAt": self._now(),
            "lastUsedAt": None,
        }
        self._keys.append(record)
        self._persist()
        return {"key": key, "record": _view(record)}

    def update(self, key_id: str, patch: Mapping[str, Any]) -> dict[str, Any]:
        """Apply ``name``, ``enabled`` and ``models`` of ``patch``; absent fields stay."""
        record = self._record(key_id)
        changes: dict[str, Any] = {}
        if patch.get("name") is not None:
            changes["name"] = _name(patch["name"])
        if patch.get("enabled") is not None:
            if not isinstance(patch["enabled"], bool):
                raise KeyStoreError("invalid", "enabled must be a boolean")
            changes["enabled"] = patch["enabled"]
        if "models" in patch:
            changes["models"] = _models(patch["models"])
        record.update(changes)
        self._persist()
        return _view(record)

    def remove(self, key_id: str) -> None:
        self._keys.remove(self._record(key_id))
        self._persist()

    def verify(self, presented: str | None) -> dict[str, Any] | None:
        """The view of the enabled key equal to ``presented``; every stored key is compared."""
        if not presented:
            return None
        actual = presented.encode()
        match = None
        for record in self._keys:
            if hmac.compare_digest(record["key"].encode(), actual) and record["enabled"]:
                match = record
        return None if match is None else _view(match)

    def touch(self, key_id: str) -> None:
        record = next((entry for entry in self._keys if entry["id"] == key_id), None)
        if record is None:
            return
        now = self._now()
        if record["lastUsedAt"] is not None and now - record["lastUsedAt"] < TOUCH_INTERVAL_MS:
            return
        record["lastUsedAt"] = now
        self._persist()


def presented_key(headers: Mapping[str, str]) -> str | None:
    match = BEARER.match(headers.get("authorization") or "")
    if match:
        return match.group(1)
    return (headers.get("x-api-key") or "").strip() or None
