from __future__ import annotations

import base64
import contextlib
import json
import re
import secrets
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx

from pyxis_harness import package_toml

from .capture import MAX_CAPTURED_LENGTH, MAX_PATH_LENGTH
from .protocol import (
    DEFAULT_HISTORY_LIMIT,
    DEFAULT_TIMEOUT_MS,
    HEADER_NAME,
    HTTP_AUTH_TYPES,
    HTTP_BODY_MODES,
    HTTP_CAPTURE_REFRESH,
    HTTP_CAPTURE_SOURCES,
    MAX_CAPTURE_RULES,
    MAX_CAPTURE_TTL_SECONDS,
    MAX_HISTORY_LIMIT,
    MAX_TIMEOUT_MS,
    MIN_HISTORY_LIMIT,
    MIN_TIMEOUT_MS,
    VARIABLE,
    VARIABLE_NAME,
    is_method,
)

_CFG = package_toml(__file__)["store"]
MAX_ENTRIES: int = _CFG["MAX_ENTRIES"]
MAX_HOSTS: int = _CFG["MAX_HOSTS"]
MAX_VALUE_LENGTH: int = _CFG["MAX_VALUE_LENGTH"]
MAX_REQUESTS_PER_TARGET: int = _CFG["MAX_REQUESTS_PER_TARGET"]
MAX_REQUEST_ROWS: int = _CFG["MAX_REQUEST_ROWS"]
MAX_REQUEST_BODY_BYTES: int = _CFG["MAX_REQUEST_BODY_BYTES"]
MAX_REQUEST_NAME: int = _CFG["MAX_REQUEST_NAME"]
MAX_REQUEST_PATH: int = _CFG["MAX_REQUEST_PATH"]
MAX_CAPTURE_NAME: int = _CFG["MAX_CAPTURE_NAME"]
FORBIDDEN_HEADERS: frozenset[str] = frozenset(_CFG["FORBIDDEN_HEADERS"])

FORMAT_VERSION = 1
DEFAULT_SETTINGS = {"agentTools": False, "historyLimit": DEFAULT_HISTORY_LIMIT}
NAME_MAX = 64
NAME_PUNCTUATION = " ._-"
NAME_RULE = "name may contain letters, digits, spaces, dots, hyphens and underscores (max 64)"
# Hostname or ``*.`` wildcard prefix: labels of letters, digits and hyphens, or a bracketed IPv6 literal.
HOST_PATTERN = re.compile(
    r"^(\*\.)?([a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)(\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)*$|^\[[0-9a-f:.]+\]$",
    re.IGNORECASE,
)
LINE_BREAK = re.compile(r"[\r\n]")
CONTROL = re.compile(r"[\x00-\x1f\x7f]")
SECRET_FIELDS = {"bearer": "token", "basic": "password", "header": "value", "query": "value"}


class StoreError(ValueError):
    """A target, request or setting is invalid, or the addressed record does not exist."""


def now_ms() -> int:
    return int(time.time() * 1000)


def _text(value: Any) -> str:
    return value if isinstance(value, str) else ""


def _is_number(value: Any) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool)


def write_private(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.chmod(0o600)
    tmp.replace(path)


# ---------------------------------------------------------------------- target fields
def normalize_base_url(value: Any) -> str:
    """http(s) only, no credentials, no query or fragment, no trailing slash."""
    text = _text(value).strip()
    if not text:
        raise StoreError("baseUrl is required")
    try:
        url = httpx.URL(text)
    except (httpx.InvalidURL, ValueError) as exc:
        raise StoreError("baseUrl must be a full URL, e.g. https://api.example.com/v1") from exc
    if not url.scheme or not url.host:
        raise StoreError("baseUrl must be a full URL, e.g. https://api.example.com/v1")
    if url.scheme not in ("http", "https"):
        raise StoreError("baseUrl must be an http(s) URL")
    if url.userinfo:
        raise StoreError("baseUrl must not embed credentials; use the auth setting")
    if url.query or url.fragment:
        raise StoreError("baseUrl must not contain a query or fragment")
    return f"{url.scheme}://{url.netloc.decode()}{url.path.rstrip('/')}"


def _valid_name(name: str) -> bool:
    return (
        0 < len(name) <= NAME_MAX
        and name[0].isalnum()
        and all(char.isalnum() or char in NAME_PUNCTUATION for char in name)
    )


def _default_name(base_url: str) -> str:
    host = httpx.URL(base_url).netloc.decode()
    return "".join(c if c.isalnum() or c in NAME_PUNCTUATION else "-" for c in host)[:NAME_MAX] or "api"


def _unique_name(wanted: str, taken: list[str]) -> str:
    lower = {name.lower() for name in taken}
    if wanted.lower() not in lower:
        return wanted
    suffix = 2
    while f"{wanted} {suffix}".lower() in lower:
        suffix += 1
    return f"{wanted} {suffix}"


def _map(value: Any, what: str, key_rule: re.Pattern[str], forbidden: frozenset[str] = frozenset()) -> dict[str, str]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise StoreError(f"{what} must be an object of strings")
    if len(value) > MAX_ENTRIES:
        raise StoreError(f"{what}: at most {MAX_ENTRIES} entries")
    out: dict[str, str] = {}
    for raw_key, item in value.items():
        key = str(raw_key).strip()
        if not key:
            continue
        if not key_rule.match(key):
            raise StoreError(f'{what}: invalid name "{key}"')
        if key.lower() in forbidden:
            raise StoreError(f'{what}: "{key}" is set by the transport and cannot be configured')
        if not isinstance(item, str):
            raise StoreError(f'{what}: value of "{key}" must be a string')
        if len(item) > MAX_VALUE_LENGTH:
            raise StoreError(f'{what}: value of "{key}" is too long')
        if LINE_BREAK.search(item):
            raise StoreError(f'{what}: value of "{key}" must not contain line breaks')
        out[key] = item
    return out


def normalize_headers(value: Any) -> dict[str, str]:
    return _map(value, "headers", HEADER_NAME, FORBIDDEN_HEADERS)


def normalize_variables(value: Any) -> dict[str, str]:
    return _map(value, "variables", VARIABLE_NAME)


def normalize_secrets(
    value: Any, previous: dict[str, str] | None = None, allow_missing: bool = False
) -> dict[str, str]:
    """
    Secret variables of a payload; an empty value takes the value ``previous`` stores under that name.
    ``allow_missing`` keeps a value that is neither given nor stored empty (an imported target).
    """
    out: dict[str, str] = {}
    for name, given in _map(value, "secrets", VARIABLE_NAME).items():
        kept = given or (previous or {}).get(name) or ""
        if not kept and not allow_missing:
            raise StoreError(f'secrets: value of "{name}" is required')
        out[name] = kept
    return out


def missing_secrets(target: dict[str, Any]) -> list[str]:
    """Names of the secret variables whose value is not stored."""
    return [name for name, value in target["secrets"].items() if not value]


def _distinct(variables: dict[str, str], secrets: dict[str, str]) -> None:
    shared = next((name for name in secrets if name in variables), None)
    if shared is not None:
        raise StoreError(f'"{shared}" is both a variable and a secret variable')


def normalize_allowed_hosts(value: Any) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise StoreError("allowedHosts must be an array")
    out: list[str] = []
    for raw in value:
        host = _text(raw).strip().lower().removesuffix(".")
        if not host:
            continue
        if not HOST_PATTERN.match(host):
            raise StoreError(f'allowedHosts: "{host}" is not a hostname or *.domain pattern')
        if host not in out:
            out.append(host)
    if len(out) > MAX_HOSTS:
        raise StoreError(f"allowedHosts: at most {MAX_HOSTS} entries")
    return out


def _integer(value: Any, low: int, high: int, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise StoreError(f"{name} must be an integer from {low} to {high}")
    return value


def normalize_auth(value: Any, previous: dict[str, Any] | None = None, allow_missing: bool = False) -> dict[str, Any]:
    """
    Validate a target's auth payload; ``previous`` supplies a secret the form left empty when the type is
    unchanged. ``allow_missing`` keeps a secret that is neither given nor stored empty (an imported target).
    """
    if value is None:
        return previous or {"type": "none"}
    if not isinstance(value, dict):
        raise StoreError("auth must be an object")
    kind = value.get("type")
    if kind not in HTTP_AUTH_TYPES:
        raise StoreError(f"auth.type must be one of {', '.join(HTTP_AUTH_TYPES)}")

    def secret(field: str) -> str:
        given = _text(value.get(field))
        if given:
            if LINE_BREAK.search(given):
                raise StoreError(f"auth.{field} must not contain line breaks")
            if len(given) > MAX_VALUE_LENGTH:
                raise StoreError(f"auth.{field} is too long")
            return given
        kept = previous.get(field) if previous is not None and previous.get("type") == kind else None
        if isinstance(kept, str) and kept:
            return kept
        if allow_missing:
            return ""
        raise StoreError(f"auth.{field} is required")

    if kind == "none":
        return {"type": "none"}
    if kind == "bearer":
        return {"type": "bearer", "token": secret("token")}
    if kind == "basic":
        username = _text(value.get("username")).strip()
        if not username or ":" in username:
            raise StoreError('auth.username is required and must not contain ":"')
        return {"type": "basic", "username": username, "password": secret("password")}
    name = _text(value.get("name")).strip()
    if kind == "header":
        if not HEADER_NAME.match(name):
            raise StoreError("auth.name must be a header name")
        if name.lower() in FORBIDDEN_HEADERS:
            raise StoreError(f'auth.name "{name}" is set by the transport')
        return {"type": "header", "name": name, "value": secret("value")}
    if not name or len(name) > 128:
        raise StoreError("auth.name must be a query parameter name")
    return {"type": "query", "name": name, "value": secret("value")}


def normalize_request_auth(value: Any) -> dict[str, Any]:
    """Auth of a saved request: the type and its fields as typed."""
    if not isinstance(value, dict):
        raise StoreError("auth must be an object")

    def text(field: str) -> str:
        given = _text(value.get(field))
        if len(given) > MAX_VALUE_LENGTH or LINE_BREAK.search(given):
            raise StoreError(f"auth.{field} is too long or contains line breaks")
        return given

    kind = value.get("type")
    if kind == "none":
        return {"type": "none"}
    if kind == "bearer":
        return {"type": "bearer", "token": text("token")}
    if kind == "basic":
        return {"type": "basic", "username": text("username"), "password": text("password")}
    if kind in ("header", "query"):
        return {"type": kind, "name": text("name").strip(), "value": text("value")}
    raise StoreError(f"auth.type must be one of {', '.join(HTTP_AUTH_TYPES)}")


def usable_request_auth(auth: dict[str, Any] | None) -> dict[str, Any] | None:
    """A request's own auth when it is complete enough to send; ``None`` otherwise."""
    kind = (auth or {}).get("type")
    if auth is None or kind in (None, "none"):
        return None
    if kind == "bearer":
        return auth if auth["token"] else None
    if kind == "basic":
        return auth if auth["username"] and ":" not in auth["username"] else None
    if kind == "header":
        name = auth["name"]
        return auth if HEADER_NAME.match(name) and name.lower() not in FORBIDDEN_HEADERS and auth["value"] else None
    return auth if auth["name"] and auth["value"] else None


def _hint(secret: str) -> str:
    """Masked hint of a secret; empty for a secret that is not stored."""
    if not secret:
        return ""
    return "••••" if len(secret) <= 6 else f"{secret[:3]}…{secret[-2:]}"


def _auth_hint(secret: str) -> str:
    """Hint of an auth secret; a value that is exactly one ``{{name}}`` reference is given as written."""
    return secret.strip() if VARIABLE.fullmatch(secret.strip()) else _hint(secret)


def auth_missing(auth: dict[str, Any]) -> bool:
    """Whether the secret of a target's auth is not stored."""
    kind = auth["type"]
    return kind in SECRET_FIELDS and not auth[SECRET_FIELDS[kind]]


def summarize_auth(auth: dict[str, Any]) -> dict[str, Any]:
    """Secret-free view: the type, non-secret names, a hint of the secret, ``missing`` when it is not stored."""
    kind = auth["type"]
    missing = {"missing": True} if auth_missing(auth) else {}
    if kind == "bearer":
        return {"type": "bearer", "hint": _auth_hint(auth["token"]), **missing}
    if kind == "basic":
        return {"type": "basic", "username": auth["username"], **missing}
    if kind in ("header", "query"):
        return {"type": kind, "name": auth["name"], "hint": _auth_hint(auth["value"]), **missing}
    return {"type": "none"}


def secrets_of(auth: dict[str, Any]) -> list[str]:
    """Secret values of an auth setting, for masking."""
    kind = auth["type"]
    secret = auth[SECRET_FIELDS[kind]] if kind in SECRET_FIELDS else ""
    if not secret:
        return []
    if kind == "basic":
        return [secret, base64.b64encode(f"{auth['username']}:{secret}".encode()).decode()]
    return [secret]


def summarize(target: dict[str, Any]) -> dict[str, Any]:
    """Secret-free projection of a target for the page and the agent."""
    return {
        **{k: target[k] for k in ("id", "name", "baseUrl")},
        "auth": summarize_auth(target["auth"]),
        "headers": dict(target["headers"]),
        "variables": dict(target["variables"]),
        "secrets": {name: _hint(value) for name, value in target["secrets"].items()},
        "allowedHosts": list(target["allowedHosts"]),
        **{k: target[k] for k in ("allowMutations", "allowPrivate", "timeoutMs", "createdAt", "updatedAt")},
    }


def build_target(
    payload: dict[str, Any], taken: list[str], previous: dict[str, Any] | None = None, allow_missing: bool = False
) -> dict[str, Any]:
    """
    A validated target from a payload. ``previous`` supplies the fields the payload leaves out, the secrets it
    leaves empty, the id and the creation time; ``taken``: names of the other targets. ``allow_missing`` keeps a
    secret that is neither given nor stored empty (an imported target).
    """

    def field(name: str, normalize: Callable[[Any], Any]) -> Any:
        return previous[name] if previous is not None and name not in payload else normalize(payload.get(name))

    def switch(name: str) -> bool:
        given = payload.get(name)
        return given if isinstance(given, bool) else previous is not None and previous[name]

    base_url = field("baseUrl", normalize_base_url)
    name = field("name", lambda wanted: _text(wanted).strip())
    if name and not _valid_name(name):
        raise StoreError(NAME_RULE)
    variables = field("variables", normalize_variables)
    stored = previous["secrets"] if previous is not None else None
    secret_variables = field("secrets", lambda value: normalize_secrets(value, stored, allow_missing))
    _distinct(variables, secret_variables)
    now = now_ms()
    return {
        "id": previous["id"] if previous is not None else secrets.token_hex(6),
        "name": _unique_name(name or _default_name(base_url), taken),
        "baseUrl": base_url,
        "auth": normalize_auth(payload.get("auth"), previous["auth"] if previous is not None else None, allow_missing),
        "headers": field("headers", normalize_headers),
        "variables": variables,
        "secrets": secret_variables,
        "allowedHosts": field("allowedHosts", normalize_allowed_hosts),
        "allowMutations": switch("allowMutations"),
        "allowPrivate": switch("allowPrivate"),
        "timeoutMs": _integer(payload["timeoutMs"], MIN_TIMEOUT_MS, MAX_TIMEOUT_MS, "timeoutMs")
        if "timeoutMs" in payload
        else previous["timeoutMs"]
        if previous is not None
        else DEFAULT_TIMEOUT_MS,
        "createdAt": previous.get("createdAt", now) if previous is not None else now,
        "updatedAt": now,
    }


# ---------------------------------------------------------------------- targets
class TargetStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._cache: tuple[tuple[int, int], dict[str, Any]] | None = None
        self._listeners: list[Callable[[], None]] = []

    def subscribe(self, listener: Callable[[], None]) -> Callable[[], None]:
        """Call ``listener`` after each write made through this store; returns the disposer."""
        self._listeners.append(listener)
        return lambda: self._listeners.remove(listener) if listener in self._listeners else None

    def list(self) -> list[dict[str, Any]]:
        return self._load()["targets"]

    def find(self, id_or_name: str) -> dict[str, Any] | None:
        """Resolve by id, exact name, then name without regard to case."""
        targets = self.list()
        for match in (
            lambda t: t["id"] == id_or_name,
            lambda t: t["name"] == id_or_name,
            lambda t: t["name"].lower() == id_or_name.lower(),
        ):
            hit = next((t for t in targets if match(t)), None)
            if hit is not None:
                return hit
        return None

    def settings(self) -> dict[str, Any]:
        return {**DEFAULT_SETTINGS, **self._load()["settings"]}

    def set_settings(self, patch: dict[str, Any]) -> dict[str, Any]:
        file = self._load()
        settings = {**DEFAULT_SETTINGS, **file["settings"]}
        if isinstance(patch.get("agentTools"), bool):
            settings["agentTools"] = patch["agentTools"]
        if "historyLimit" in patch:
            settings["historyLimit"] = _integer(
                patch["historyLimit"], MIN_HISTORY_LIMIT, MAX_HISTORY_LIMIT, "historyLimit"
            )
        file["settings"] = settings
        self._save(file)
        return dict(settings)

    def create(self, payload: dict[str, Any]) -> dict[str, Any]:
        file = self._load()
        target = build_target(payload, [t["name"] for t in file["targets"]])
        file["targets"].append(target)
        self._save(file)
        return target

    def update(self, target_id: str, patch: dict[str, Any]) -> dict[str, Any]:
        """Apply the fields present in ``patch``; the others stay."""
        file = self._load()
        target = next((t for t in file["targets"] if t["id"] == target_id), None)
        if target is None:
            raise StoreError(f"target '{target_id}' not found")
        target.update(build_target(patch, [t["name"] for t in file["targets"] if t["id"] != target_id], target))
        self._save(file)
        return target

    def replace_all(self, targets: list[dict[str, Any]], history_limit: int | None = None) -> None:
        """Write the whole target list at once (an import); ``history_limit`` sets that setting."""
        file = self._load()
        file["targets"] = list(targets)
        if history_limit is not None:
            file["settings"] = {**DEFAULT_SETTINGS, **file["settings"], "historyLimit": history_limit}
        self._save(file)

    def delete(self, target_id: str) -> None:
        file = self._load()
        remaining = [t for t in file["targets"] if t["id"] != target_id]
        if len(remaining) == len(file["targets"]):
            raise StoreError(f"target '{target_id}' not found")
        file["targets"] = remaining
        self._save(file)

    def _empty(self) -> dict[str, Any]:
        return {"version": FORMAT_VERSION, "settings": dict(DEFAULT_SETTINGS), "targets": []}

    def _load(self) -> dict[str, Any]:
        try:
            stat = self.path.stat()
        except OSError:
            self._cache = None
            return self._empty()
        stamp = (stat.st_mtime_ns, stat.st_size)
        if self._cache is not None and self._cache[0] == stamp:
            return self._cache[1]
        try:
            parsed = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(parsed, dict) or not isinstance(parsed.get("targets"), list):
                raise ValueError("store file shape invalid")
        except (OSError, ValueError):
            self._cache = None
            with contextlib.suppress(OSError):
                self.path.replace(self.path.with_name(f"{self.path.name}.corrupt-{now_ms()}"))
            return self._empty()
        parsed["settings"] = {**DEFAULT_SETTINGS, **(parsed.get("settings") or {})}
        for target in parsed["targets"]:
            target["auth"] = target.get("auth") or {"type": "none"}
            target["headers"] = target.get("headers") or {}
            target["variables"] = target.get("variables") or {}
            target["secrets"] = target["secrets"] if isinstance(target.get("secrets"), dict) else {}
            hosts = target.get("allowedHosts")
            target["allowedHosts"] = hosts if isinstance(hosts, list) else []
            target["allowMutations"] = target.get("allowMutations") is True
            target["allowPrivate"] = target.get("allowPrivate") is True
            timeout = target.get("timeoutMs")
            target["timeoutMs"] = timeout if isinstance(timeout, int) else DEFAULT_TIMEOUT_MS
        self._cache = (stamp, parsed)
        return parsed

    def _save(self, file: dict[str, Any]) -> None:
        write_private(self.path, json.dumps(file, ensure_ascii=False, indent=2) + "\n")
        self._cache = None
        for listener in list(self._listeners):
            with contextlib.suppress(Exception):  # a listener never breaks a save
                listener()


# ---------------------------------------------------------------------- history
class HistoryStore:
    """``limit()`` is the number of exchanges kept; the file is compacted once it holds half as many again."""

    def __init__(self, path: Path, limit: Callable[[], int] = lambda: DEFAULT_HISTORY_LIMIT) -> None:
        self.path = path
        self._limit = limit
        self._entries: list[dict[str, Any]] | None = None

    def list(self, target_id: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        """Newest first; ``target_id`` narrows to one target or to the direct scope."""
        entries = self._load()
        if target_id is not None:
            entries = [e for e in entries if e["targetId"] == target_id]
        return entries[max(0, len(entries) - limit) :][::-1]

    def add(self, entry: dict[str, Any]) -> None:
        entries = self._load()
        entries.append(entry)
        limit = self._limit()
        if len(entries) > limit * 1.5:
            self._rewrite(entries[-limit:])
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self.path.touch(mode=0o600)
        with self.path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def clear(self, entry_id: str | None = None, target_id: str | None = None) -> int:
        """Remove one entry, every entry of a target, or everything; returns the number removed."""
        entries = self._load()
        keep = [
            e
            for e in entries
            if (entry_id is not None or target_id is not None)
            and (entry_id is None or e["id"] != entry_id)
            and (target_id is None or e["targetId"] != target_id)
        ]
        removed = len(entries) - len(keep)
        if removed:
            self._rewrite(keep)
        return removed

    def _load(self) -> list[dict[str, Any]]:
        if self._entries is not None:
            return self._entries
        try:
            lines = self.path.read_text(encoding="utf-8").split("\n")
        except OSError:
            lines = []
        entries = []
        for line in lines:
            if not line.strip():
                continue
            try:
                parsed = json.loads(line)
            except ValueError:
                continue  # a damaged line is skipped
            if (
                isinstance(parsed, dict)
                and isinstance(parsed.get("id"), str)
                and isinstance(parsed.get("request"), dict)
            ):
                entries.append(parsed)
        self._entries = entries[-self._limit() :]
        return self._entries

    def _rewrite(self, entries: list[dict[str, Any]]) -> None:
        write_private(self.path, "".join(json.dumps(e, ensure_ascii=False) + "\n" for e in entries))
        self._entries = entries


# ---------------------------------------------------------------------- saved requests
def _rows(value: Any, what: str) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise StoreError(f"{what} must be an array of rows")
    if len(value) > MAX_REQUEST_ROWS:
        raise StoreError(f"{what}: at most {MAX_REQUEST_ROWS} rows")
    rows = []
    for raw in value:
        row = raw if isinstance(raw, dict) else {}
        key, item = _text(row.get("key")), _text(row.get("value"))
        if len(key) > MAX_VALUE_LENGTH or len(item) > MAX_VALUE_LENGTH:
            raise StoreError(f"{what}: a row is too long")
        rows.append({"key": key, "value": item, "enabled": row.get("enabled") is not False})
    return rows


def _stored_capture(rule: dict[str, Any]) -> dict[str, Any]:
    """A capture rule with every field present; absent or invalid fields take their defaults."""
    ttl, ttl_path = rule.get("ttlSeconds"), rule.get("ttlPath")
    if isinstance(ttl, float) and ttl.is_integer():
        ttl = int(ttl)
    timed = isinstance(ttl, int) and not isinstance(ttl, bool) and ttl > 0
    pathed = isinstance(ttl_path, str) and len(ttl_path) <= MAX_PATH_LENGTH and not LINE_BREAK.search(ttl_path)
    return {
        "name": _text(rule.get("name")),
        "source": rule["source"] if rule.get("source") in HTTP_CAPTURE_SOURCES else "body",
        "path": _text(rule.get("path")),
        "enabled": rule.get("enabled") is not False,
        "ttlSeconds": min(ttl, MAX_CAPTURE_TTL_SECONDS) if timed else 0,
        "ttlPath": ttl_path if pathed else "",
        "refresh": rule["refresh"] if rule.get("refresh") in HTTP_CAPTURE_REFRESH else "off",
    }


def _captures(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise StoreError("captures must be an array of rules")
    if len(value) > MAX_CAPTURE_RULES:
        raise StoreError(f"captures: at most {MAX_CAPTURE_RULES} rules")
    rules = []
    for raw in value:
        rule = _stored_capture(raw if isinstance(raw, dict) else {})
        name, path = rule["name"], rule["path"]
        if len(name) > MAX_CAPTURE_NAME or len(path) > MAX_PATH_LENGTH or LINE_BREAK.search(name + path):
            raise StoreError("captures: a rule is too long or contains line breaks")
        rules.append(rule)
    return rules


def _request_fields(payload: dict[str, Any]) -> dict[str, Any]:
    """Validated fields of a saved request payload; absent fields stay absent."""
    out: dict[str, Any] = {}
    if payload.get("name") is not None:
        name = _text(payload["name"]).strip()
        if len(name) > MAX_REQUEST_NAME or CONTROL.search(name):
            raise StoreError(f"name: at most {MAX_REQUEST_NAME} printable characters")
        out["name"] = name
    if payload.get("method") is not None:
        method = str(payload["method"]).upper()
        if not is_method(method):
            raise StoreError(f"unsupported method '{payload['method']}'")
        out["method"] = method
    if payload.get("path") is not None:
        path = _text(payload["path"])
        if len(path) > MAX_REQUEST_PATH or LINE_BREAK.search(path):
            raise StoreError("path is too long or contains line breaks")
        out["path"] = path
    for field in ("query", "headers", "form"):
        if payload.get(field) is not None:
            out[field] = _rows(payload[field], field)
    if payload.get("captures") is not None:
        out["captures"] = _captures(payload["captures"])
    if payload.get("auth") is not None:
        out["auth"] = normalize_request_auth(payload["auth"])
    if payload.get("bodyMode") is not None:
        if payload["bodyMode"] not in HTTP_BODY_MODES:
            raise StoreError(f"bodyMode must be one of {', '.join(HTTP_BODY_MODES)}")
        out["bodyMode"] = payload["bodyMode"]
    if payload.get("body") is not None:
        body = _text(payload["body"])
        if len(body.encode()) > MAX_REQUEST_BODY_BYTES:
            raise StoreError(f"body: at most {MAX_REQUEST_BODY_BYTES // 1024} KiB")
        out["body"] = body
    return out


def build_request(target_id: str, payload: dict[str, Any], request_id: str | None = None) -> dict[str, Any]:
    """A saved request of a scope from a payload: its validated fields over the defaults; a new id without one."""
    now = now_ms()
    return {
        "id": request_id or secrets.token_hex(6),
        "targetId": target_id,
        "name": "",
        "method": "GET",
        "path": "",
        "query": [],
        "headers": [],
        "auth": {"type": "none"},
        "bodyMode": "none",
        "body": "",
        "form": [],
        "captures": [],
        **_request_fields(payload),
        "createdAt": now,
        "updatedAt": now,
    }


class RequestStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._entries: list[dict[str, Any]] | None = None

    def list(self, target_id: str | None = None) -> list[dict[str, Any]]:
        """Requests of one target or scope, or all of them, in creation order."""
        entries = self._load()
        return list(entries) if target_id is None else [r for r in entries if r["targetId"] == target_id]

    def get(self, request_id: str) -> dict[str, Any] | None:
        return next((r for r in self._load() if r["id"] == request_id), None)

    def _room(self, target_id: str) -> None:
        if sum(r["targetId"] == target_id for r in self._load()) >= MAX_REQUESTS_PER_TARGET:
            raise StoreError(f"at most {MAX_REQUESTS_PER_TARGET} requests per target")

    def create(self, payload: dict[str, Any]) -> dict[str, Any]:
        target_id = _text(payload.get("targetId")).strip()
        if not target_id:
            raise StoreError("targetId is required")
        self._room(target_id)
        request = build_request(target_id, payload)
        self._save([*self._load(), request])
        return request

    def update(self, request_id: str, patch: dict[str, Any]) -> dict[str, Any]:
        """Apply the fields present in ``patch``; a ``targetId`` moves the request to that target."""
        request = self.get(request_id)
        if request is None:
            raise StoreError(f"request '{request_id}' not found")
        target_id = request["targetId"] if patch.get("targetId") is None else _text(patch["targetId"]).strip()
        if not target_id:
            raise StoreError("targetId must not be empty")
        if target_id != request["targetId"]:
            self._room(target_id)
        request.update(_request_fields(patch), targetId=target_id, updatedAt=now_ms())
        self._save(self._load())
        return request

    def delete(self, request_id: str) -> None:
        if self.get(request_id) is None:
            raise StoreError(f"request '{request_id}' not found")
        self._save([r for r in self._load() if r["id"] != request_id])

    def replace_all(self, requests: list[dict[str, Any]]) -> None:
        """Write the whole request list at once (an import)."""
        self._save(list(requests))

    def delete_by_target(self, target_id: str) -> int:
        """Remove every request of a target; returns the count."""
        entries = self._load()
        keep = [r for r in entries if r["targetId"] != target_id]
        if len(keep) != len(entries):
            self._save(keep)
        return len(entries) - len(keep)

    def _load(self) -> list[dict[str, Any]]:
        if self._entries is not None:
            return self._entries
        try:
            parsed = json.loads(self.path.read_text(encoding="utf-8"))
            stored = parsed.get("requests") if isinstance(parsed, dict) else None
        except (OSError, ValueError):
            stored = None
        entries = []
        for raw in stored if isinstance(stored, list) else []:
            if (
                not isinstance(raw, dict)
                or not isinstance(raw.get("id"), str)
                or not isinstance(raw.get("targetId"), str)
            ):
                continue
            captures = raw["captures"] if isinstance(raw.get("captures"), list) else []
            entries.append(
                {
                    **raw,
                    "name": _text(raw.get("name")),
                    "method": raw["method"] if is_method(raw.get("method")) else "GET",
                    "path": _text(raw.get("path")),
                    "query": raw["query"] if isinstance(raw.get("query"), list) else [],
                    "headers": raw["headers"] if isinstance(raw.get("headers"), list) else [],
                    "auth": raw["auth"] if isinstance(raw.get("auth"), dict) else {"type": "none"},
                    "bodyMode": raw["bodyMode"] if raw.get("bodyMode") in HTTP_BODY_MODES else "none",
                    "body": _text(raw.get("body")),
                    "form": raw["form"] if isinstance(raw.get("form"), list) else [],
                    "captures": [_stored_capture(rule if isinstance(rule, dict) else {}) for rule in captures],
                }
            )
        self._entries = entries
        return entries

    def _save(self, entries: list[dict[str, Any]]) -> None:
        text = json.dumps({"version": FORMAT_VERSION, "requests": entries}, ensure_ascii=False, indent=2) + "\n"
        write_private(self.path, text)
        self._entries = entries


# ---------------------------------------------------------------------- captured values
def _stored_value(entry: dict[str, Any]) -> dict[str, Any]:
    """A stored captured value with every field typed; ``expiresAt`` only when it is a number."""
    request_id, at, expires = entry.get("requestId"), entry.get("at"), entry.get("expiresAt")
    value = {
        "value": entry["value"],
        "requestId": request_id if isinstance(request_id, str) else "",
        "at": at if _is_number(at) else 0,
    }
    return {**value, "expiresAt": expires} if _is_number(expires) else value


class ValueStore:
    """
    Captured variable values by scope: a target id, or the direct scope. The values are secrets: they stay in the
    store; :meth:`list` gives names and hints.
    """

    def __init__(self, path: Path) -> None:
        self.path = path
        self._scopes: dict[str, dict[str, dict[str, Any]]] | None = None

    def map(self, scope_id: str) -> dict[str, str]:
        """Values of a scope by variable name."""
        return {name: entry["value"] for name, entry in self._load().get(scope_id, {}).items()}

    def entry(self, scope_id: str, name: str) -> dict[str, Any] | None:
        """One value of a scope with its origin and expiry: ``value``, ``requestId``, ``at``, ``expiresAt``."""
        stored = self._load().get(scope_id, {}).get(name)
        return None if stored is None else dict(stored)

    def list(self, scope_id: str) -> list[dict[str, Any]]:
        """Secret-free view of a scope's values, by name."""
        scope = self._load().get(scope_id, {})
        return [
            {"name": name, "hint": _hint(entry["value"]), **{k: v for k, v in entry.items() if k != "value"}}
            for name, entry in sorted(scope.items(), key=lambda item: (item[0].casefold(), item[0]))
        ]

    def set(
        self, scope_id: str, values: dict[str, str], request_id: str, lifetimes: dict[str, int] | None = None
    ) -> None:
        """
        Write values captured from one saved request. ``lifetimes``: lifetime in ms by variable name; a value
        without one does not expire.
        """
        kept = {k: v for k, v in values.items() if VARIABLE_NAME.match(k) and len(v) <= MAX_CAPTURED_LENGTH}
        if not kept:
            return
        scopes = self._load()
        scope = scopes.setdefault(scope_id, {})
        at = now_ms()
        for name, value in kept.items():
            lifetime = (lifetimes or {}).get(name, 0)
            scope[name] = {"value": value, "requestId": request_id, "at": at}
            if lifetime > 0:
                scope[name]["expiresAt"] = at + lifetime
        self._save(scopes)

    def delete(self, scope_id: str, name: str | None = None) -> int:
        """Remove one value of a scope, or the whole scope; returns the count."""
        scopes = self._load()
        scope = scopes.get(scope_id, {})
        removed = len(scope) if name is None else int(name in scope)
        if not removed:
            return 0
        if name is not None:
            del scope[name]
        if name is None or not scope:
            del scopes[scope_id]
        self._save(scopes)
        return removed

    def _load(self) -> dict[str, dict[str, dict[str, Any]]]:
        if self._scopes is not None:
            return self._scopes
        try:
            parsed = json.loads(self.path.read_text(encoding="utf-8"))
            stored = parsed.get("scopes") if isinstance(parsed, dict) else None
        except (OSError, ValueError):
            stored = None
        scopes: dict[str, dict[str, dict[str, Any]]] = {}
        for scope_id, raw in (stored if isinstance(stored, dict) else {}).items():
            scope = {
                name: _stored_value(entry)
                for name, entry in (raw if isinstance(raw, dict) else {}).items()
                if VARIABLE_NAME.match(name) and isinstance(entry, dict) and isinstance(entry.get("value"), str)
            }
            if scope:
                scopes[scope_id] = scope
        self._scopes = scopes
        return scopes

    def _save(self, scopes: dict[str, dict[str, dict[str, Any]]]) -> None:
        text = json.dumps({"version": FORMAT_VERSION, "scopes": scopes}, ensure_ascii=False, indent=2) + "\n"
        write_private(self.path, text)
        self._scopes = scopes
