"""Credential store: secrets referenced by name from configuration, never written into it.

| reference resolution | source                                              |
|----------------------|-----------------------------------------------------|
| 1                    | environment variable of that name                   |
| 2                    | ``credentials.yaml`` in the profile directory (0600) |

A configuration names a credential (``api_key_env: OPENAI_API_KEY``); the value lives in the environment or in the
store.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import yaml

REFERENCE = re.compile(r"^[A-Z][A-Z0-9_]{0,127}$")


def reference_for(route: str) -> str:
    """``<ROUTE>_API_KEY`` for a provider route id (``openai-codex`` → ``OPENAI_CODEX_API_KEY``)."""
    stem = re.sub(r"[^A-Z0-9]+", "_", route.upper()).strip("_") or "PROVIDER"
    if stem[0].isdigit():
        stem = "P_" + stem
    return f"{stem}_API_KEY"


class CredentialStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    # ------------------------------------------------------------------ file
    def _read(self) -> dict[str, str]:
        try:
            data = yaml.safe_load(self.path.read_text(encoding="utf-8")) or {}
        except FileNotFoundError:
            return {}
        if not isinstance(data, dict):
            raise ValueError(f"{self.path} must be a mapping")
        return {str(k): str(v) for k, v in data.items() if v is not None}

    def _write(self, data: dict[str, str]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(
            "# Credentials referenced by name from the profile configuration. Keep private.\n"
            + yaml.safe_dump(data, sort_keys=True),
            encoding="utf-8",
        )
        os.chmod(tmp, 0o600)
        os.replace(tmp, self.path)

    # ------------------------------------------------------------------ access
    def names(self) -> list[str]:
        return sorted(self._read())

    def get(self, reference: str | None) -> str | None:
        """Value for ``reference``: environment first, then the store; ``None`` when neither has it."""
        if not reference:
            return None
        value = os.environ.get(reference)
        if value:
            return value
        return self._read().get(reference) or None

    def describe(self, reference: str | None) -> dict[str, Any]:
        """``configured`` and ``source`` (``env``, ``store`` or ``None``) without the value."""
        if not reference:
            return {"reference": None, "configured": False, "source": None}
        if os.environ.get(reference):
            return {"reference": reference, "configured": True, "source": "env"}
        if self._read().get(reference):
            return {"reference": reference, "configured": True, "source": "store"}
        return {"reference": reference, "configured": False, "source": None}

    def set(self, reference: str, value: str) -> None:
        if not REFERENCE.match(reference):
            raise ValueError(f"invalid credential reference {reference!r}: uppercase letters, digits and underscores")
        value = value.strip()
        if not value or not all(0x21 <= ord(c) <= 0x7E for c in value):
            raise ValueError("a credential is non-empty printable ASCII without spaces")
        data = self._read()
        data[reference] = value
        self._write(data)

    def delete(self, reference: str) -> bool:
        data = self._read()
        if reference not in data:
            return False
        del data[reference]
        self._write(data)
        return True


__all__ = ["REFERENCE", "CredentialStore", "reference_for"]
