"""Connection profiles (``<profile data>/toolkit/rdb.json``) and the agent-access setting; passwords live in the
profile credential store under ``RDB_<ID>``."""

from __future__ import annotations

import json
import os
import re
import secrets
import threading
import time
from pathlib import Path
from typing import Any

from .engine import DEFAULT_PORT, KINDS, TARGETS, parse_hosts

NAME_RE = re.compile(r"^[^\W_][\w .-]{0,63}$", re.U)
HOST_RE = re.compile(r"^(?:\[[0-9a-fA-F:.]+\]|[0-9a-fA-F:]*:[0-9a-fA-F:]*:[0-9a-fA-F.:]*|[A-Za-z0-9._-]+)$")
SUMMARY_FIELDS = (
    "id",
    "name",
    "kind",
    "file",
    "host",
    "port",
    "database",
    "user",
    "ssl",
    "targetSessionAttrs",
    "loadBalanceHosts",
    "allowWrite",
    "createdAt",
    "updatedAt",
)


class StoreError(ValueError):
    pass


def ref(pid: str) -> str:
    """Credential-store reference of a profile's secret (references are upper-case identifiers)."""
    return f"RDB_{pid.upper()}"


def validate(profile: dict[str, Any]) -> None:
    name = profile.get("name") or ""
    if name and not NAME_RE.match(name):
        raise StoreError("name may contain letters, digits, spaces, dots, hyphens and underscores (max 64)")
    kind = profile.get("kind")
    if kind not in KINDS:
        raise StoreError("kind must be sqlite, postgres, gaussdb or mysql")
    if kind == "sqlite":
        if not (profile.get("file") or "").strip():
            raise StoreError("file is required for sqlite")
        return
    port = profile.get("port")
    if port is not None and (not isinstance(port, int) or isinstance(port, bool) or not 1 <= port <= 65535):
        raise StoreError("port must be an integer in 1..65535")
    entries = [h for h in re.split(r"[\s,]+", (profile.get("host") or "").strip()) if h]
    for entry in entries:
        if not HOST_RE.match(entry):
            if re.match(r"^[A-Za-z0-9._-]+:\d+$", entry):
                raise StoreError(f"'{entry}': hosts take no port; all nodes use the port field")
            raise StoreError(f"invalid host '{entry}'")
    if not entries:
        raise StoreError("host is required")
    if profile.get("targetSessionAttrs") not in TARGETS:
        raise StoreError("targetSessionAttrs must be one of any, read-write, read-only, primary, standby, prefer-standby")
    if not (profile.get("database") or "").strip():
        raise StoreError("database is required")
    if not (profile.get("user") or "").strip():
        raise StoreError("user is required")


def default_name(profile: dict[str, Any]) -> str:
    if profile["kind"] == "sqlite":
        return os.path.basename(profile["file"].rstrip("/")) or "sqlite"
    hosts = parse_hosts(profile["host"])
    return f"{profile['database']}@{hosts[0] if hosts else ''}"


def unique_name(name: str, taken: list[str]) -> str:
    lower = {t.lower() for t in taken}
    if name.lower() not in lower:
        return name
    n = 2
    while f"{name} {n}".lower() in lower:
        n += 1
    return f"{name} {n}"


class ProfileStore:
    def __init__(self, path: Path, credentials: Any) -> None:
        self.path = path
        self.credentials = credentials
        self._lock = threading.RLock()
        self._listeners: list[Any] = []

    def _read(self) -> dict[str, Any]:
        try:
            data = json.loads(self.path.read_text("utf-8"))
        except FileNotFoundError:
            return {"version": 1, "settings": {"agentTools": False}, "profiles": []}
        except ValueError:
            corrupt = self.path.with_name(f"{self.path.name}.corrupt-{int(time.time() * 1000)}")
            self.path.rename(corrupt)
            return {"version": 1, "settings": {"agentTools": False}, "profiles": []}
        if not isinstance(data, dict) or not isinstance(data.get("profiles"), list):
            return {"version": 1, "settings": {"agentTools": False}, "profiles": []}
        data.setdefault("settings", {})
        data["settings"] = {"agentTools": False, **data["settings"]}
        for p in data["profiles"]:
            p.setdefault("targetSessionAttrs", "any")
            p.setdefault("loadBalanceHosts", False)
            p.setdefault("allowWrite", False)
            p.setdefault("ssl", False)
        return data

    def _write(self, data: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", "utf-8")
        os.chmod(tmp, 0o600)
        tmp.replace(self.path)
        for fn in self._listeners:
            try:
                fn()
            except Exception:  # noqa: BLE001
                pass

    def subscribe(self, fn: Any) -> None:
        self._listeners.append(fn)

    # ------------------------------------------------------------------ reads
    def settings(self) -> dict[str, Any]:
        with self._lock:
            return dict(self._read()["settings"])

    def profiles(self) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(p) for p in self._read()["profiles"]]

    def find(self, id_or_name: str) -> dict[str, Any] | None:
        profiles = self.profiles()
        for p in profiles:
            if p["id"] == id_or_name:
                return p
        for p in profiles:
            if p["name"] == id_or_name:
                return p
        low = id_or_name.lower()
        for p in profiles:
            if p["name"].lower() == low:
                return p
        return None

    def password(self, pid: str) -> str:
        return self.credentials.get(ref(pid)) or ""

    @staticmethod
    def summary(profile: dict[str, Any]) -> dict[str, Any]:
        return {k: profile.get(k) for k in SUMMARY_FIELDS}

    # ------------------------------------------------------------------ writes
    def set_settings(self, **fields: Any) -> dict[str, Any]:
        with self._lock:
            data = self._read()
            for k, v in fields.items():
                if isinstance(v, bool):
                    data["settings"][k] = v
            self._write(data)
            return dict(data["settings"])

    def _normalize(self, payload: dict[str, Any], existing: dict[str, Any] | None) -> dict[str, Any]:
        base = dict(existing or {})
        kind = payload.get("kind", base.get("kind"))
        merged = {
            "kind": kind,
            "name": (payload.get("name") if payload.get("name") is not None else base.get("name", "")) or "",
            "file": (payload.get("file") if payload.get("file") is not None else base.get("file", "")) or "",
            "host": (payload.get("host") if payload.get("host") is not None else base.get("host", "")) or "",
            "port": payload.get("port") if payload.get("port") is not None else base.get("port"),
            "database": (payload.get("database") if payload.get("database") is not None else base.get("database", "")) or "",
            "user": (payload.get("user") if payload.get("user") is not None else base.get("user", "")) or "",
            "ssl": bool(payload.get("ssl", base.get("ssl", False))),
            "targetSessionAttrs": payload.get("targetSessionAttrs") or base.get("targetSessionAttrs") or "any",
            "loadBalanceHosts": bool(payload.get("loadBalanceHosts", base.get("loadBalanceHosts", False))),
            "allowWrite": bool(payload.get("allowWrite", base.get("allowWrite", False))),
        }
        merged["name"] = str(merged["name"]).strip()
        if kind == "sqlite":
            merged.update(
                file=str(merged["file"]).strip(), host="", port=0, database="", user="", targetSessionAttrs="any", loadBalanceHosts=False
            )
        else:
            if merged["port"] in (None, "", 0):
                merged["port"] = DEFAULT_PORT.get(kind, 0)
            merged["file"] = ""
            merged["host"] = ", ".join(h for h in re.split(r"[\s,]+", str(merged["host"]).strip()) if h)
            merged["database"] = str(merged["database"]).strip()
            merged["user"] = str(merged["user"]).strip()
        validate(merged)
        return merged

    def create(self, payload: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            data = self._read()
            profile = self._normalize(payload, None)
            now = int(time.time() * 1000)
            profile["id"] = secrets.token_hex(6)
            profile["name"] = unique_name(profile["name"] or default_name(profile), [p["name"] for p in data["profiles"]])
            profile["createdAt"] = now
            profile["updatedAt"] = now
            data["profiles"].append(profile)
            if profile["kind"] != "sqlite":
                self.credentials.set(ref(profile["id"]), str(payload.get("password") or ""))
            self._write(data)
            return self.summary(profile)

    def update(self, pid: str, payload: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            data = self._read()
            existing = next((p for p in data["profiles"] if p["id"] == pid), None)
            if existing is None:
                raise StoreError(f"profile '{pid}' not found")
            profile = self._normalize(payload, existing)
            profile["id"] = pid
            profile["createdAt"] = existing.get("createdAt")
            profile["updatedAt"] = int(time.time() * 1000)
            profile["name"] = unique_name(profile["name"] or default_name(profile), [p["name"] for p in data["profiles"] if p["id"] != pid])
            data["profiles"] = [profile if p["id"] == pid else p for p in data["profiles"]]
            if payload.get("password"):
                self.credentials.set(ref(pid), str(payload["password"]))
            self._write(data)
            return self.summary(profile)

    def delete(self, pid: str) -> None:
        with self._lock:
            data = self._read()
            if not any(p["id"] == pid for p in data["profiles"]):
                raise StoreError(f"profile '{pid}' not found")
            data["profiles"] = [p for p in data["profiles"] if p["id"] != pid]
            self._write(data)
            try:
                self.credentials.delete(ref(pid))
            except Exception:  # noqa: BLE001
                pass
