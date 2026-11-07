"""Bucket profiles (``<profile data>/toolkit/s3.json``) and the agent-access setting; secret keys live in the profile
credential store under ``S3_<ID>``."""

from __future__ import annotations

import json
import os
import re
import secrets
import threading
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

NAME_RE = re.compile(r"^[^\W_][\w .-]{0,63}$", re.U)
BUCKET_RE = re.compile(r"^[a-z0-9][a-z0-9.-]{1,62}$")
SUMMARY_FIELDS = (
    "id",
    "name",
    "bucket",
    "endpoint",
    "region",
    "accessKeyHint",
    "pathStyle",
    "prefix",
    "createdAt",
    "updatedAt",
)


class StoreError(ValueError):
    pass


def ref(pid: str) -> str:
    """Credential-store reference of a profile's secret (references are upper-case identifiers)."""
    return f"S3_{pid.upper()}"


def normalize_prefix(prefix: str) -> str:
    p = (prefix or "").strip().lstrip("/")
    return p + "/" if p and not p.endswith("/") else p


def validate(profile: dict[str, Any], secret: str | None) -> None:
    name = profile.get("name") or ""
    if name and not NAME_RE.match(name):
        raise StoreError("name may contain letters, digits, spaces, dots, hyphens and underscores (max 64)")
    bucket = (profile.get("bucket") or "").strip()
    if not bucket:
        raise StoreError("bucket is required")
    if not BUCKET_RE.match(bucket):
        raise StoreError("bucket name looks invalid (lowercase letters, digits, dots, hyphens)")
    if not (profile.get("accessKeyId") or "").strip():
        raise StoreError("accessKeyId is required")
    if secret == "":
        raise StoreError("secretAccessKey is required")
    endpoint = profile.get("endpoint") or ""
    if endpoint:
        parsed = urlparse(endpoint)
        if not parsed.scheme or not parsed.netloc:
            raise StoreError("endpoint must be a full URL, e.g. https://s3.example.com")
        if parsed.scheme not in ("http", "https"):
            raise StoreError("endpoint must be an http(s) URL")
    if "pathStyle" in profile and not isinstance(profile["pathStyle"], bool):
        raise StoreError("pathStyle must be a boolean")


def unique_name(name: str, taken: list[str]) -> str:
    lower = {t.lower() for t in taken}
    if name.lower() not in lower:
        return name
    n = 2
    while f"{name} {n}".lower() in lower:
        n += 1
    return f"{name} {n}"


def key_hint(access_key: str) -> str:
    return access_key[:4] + "…" + access_key[-2:] if access_key else ""


class ProfileStore:
    def __init__(self, path: Path, credentials: Any) -> None:
        self.path = path
        self.credentials = credentials
        self._lock = threading.RLock()
        self._listeners: list[Any] = []

    def _empty(self) -> dict[str, Any]:
        return {"version": 1, "settings": {"agentTools": False}, "profiles": []}

    def _read(self) -> dict[str, Any]:
        try:
            data = json.loads(self.path.read_text("utf-8"))
        except FileNotFoundError:
            return self._empty()
        except ValueError:
            self.path.rename(self.path.with_name(f"{self.path.name}.corrupt-{int(time.time() * 1000)}"))
            return self._empty()
        if not isinstance(data, dict) or not isinstance(data.get("profiles"), list):
            return self._empty()
        data["settings"] = {"agentTools": False, **(data.get("settings") or {})}
        for p in data["profiles"]:
            p["prefix"] = normalize_prefix(p.get("prefix") or "")
            p["endpoint"] = (p.get("endpoint") or "").rstrip("/")
            p["region"] = p.get("region") or "us-east-1"
            p.setdefault("pathStyle", True)
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

    def settings(self) -> dict[str, Any]:
        with self._lock:
            return dict(self._read()["settings"])

    def set_settings(self, **fields: Any) -> dict[str, Any]:
        with self._lock:
            data = self._read()
            for k, v in fields.items():
                if isinstance(v, bool):
                    data["settings"][k] = v
            self._write(data)
            return dict(data["settings"])

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

    def secret(self, pid: str) -> str:
        return self.credentials.get(ref(pid)) or ""

    @staticmethod
    def summary(profile: dict[str, Any]) -> dict[str, Any]:
        out = {k: profile.get(k) for k in SUMMARY_FIELDS if k != "accessKeyHint"}
        out["accessKeyHint"] = key_hint(profile.get("accessKeyId") or "")
        return out

    def _normalize(self, payload: dict[str, Any], existing: dict[str, Any] | None) -> dict[str, Any]:
        base = existing or {}
        pick = lambda k, d="": payload.get(k) if payload.get(k) is not None else base.get(k, d)  # noqa: E731
        merged = {
            "name": str(pick("name")).strip(),
            "bucket": str(pick("bucket")).strip(),
            "endpoint": str(pick("endpoint")).strip().rstrip("/"),
            "region": str(pick("region")).strip() or "us-east-1",
            "accessKeyId": str(pick("accessKeyId")).strip(),
            "prefix": normalize_prefix(str(pick("prefix"))),
        }
        if "pathStyle" in payload and payload["pathStyle"] is not None:
            merged["pathStyle"] = payload["pathStyle"]
        elif existing is not None:
            merged["pathStyle"] = base.get("pathStyle", True)
        else:
            merged["pathStyle"] = merged["endpoint"] != ""
        return merged

    def create(self, payload: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            data = self._read()
            profile = self._normalize(payload, None)
            secret = payload.get("secretAccessKey")
            validate(profile, "" if secret is None else str(secret))
            now = int(time.time() * 1000)
            profile["id"] = secrets.token_hex(6)
            profile["name"] = unique_name(profile["name"] or profile["bucket"], [p["name"] for p in data["profiles"]])
            profile["createdAt"] = now
            profile["updatedAt"] = now
            data["profiles"].append(profile)
            self.credentials.set(ref(profile["id"]), str(secret))
            self._write(data)
            return self.summary(profile)

    def update(self, pid: str, payload: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            data = self._read()
            existing = next((p for p in data["profiles"] if p["id"] == pid), None)
            if existing is None:
                raise StoreError(f"profile '{pid}' not found")
            profile = self._normalize(payload, existing)
            secret = payload.get("secretAccessKey") or None
            validate(profile, None if secret is None else str(secret))
            profile["id"] = pid
            profile["createdAt"] = existing.get("createdAt")
            profile["updatedAt"] = int(time.time() * 1000)
            profile["name"] = unique_name(
                profile["name"] or profile["bucket"], [p["name"] for p in data["profiles"] if p["id"] != pid]
            )
            data["profiles"] = [profile if p["id"] == pid else p for p in data["profiles"]]
            if secret:
                self.credentials.set(ref(pid), str(secret))
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
