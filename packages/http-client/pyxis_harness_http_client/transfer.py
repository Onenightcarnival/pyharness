from __future__ import annotations

import re
import secrets
from collections import Counter
from dataclasses import dataclass
from typing import Any

from pyxis_harness import package_toml

from .engine import CREDENTIAL_HEADERS
from .protocol import DIRECT_TARGET_ID, MAX_HISTORY_LIMIT, MIN_HISTORY_LIMIT, VARIABLE
from .store import (
    MAX_REQUESTS_PER_TARGET,
    SECRET_FIELDS,
    StoreError,
    auth_missing,
    build_request,
    build_target,
    missing_secrets,
    now_ms,
)

_CFG = package_toml(__file__)["transfer"]
BUNDLE_FORMAT: str = _CFG["BUNDLE_FORMAT"]
BUNDLE_VERSION: int = _CFG["BUNDLE_VERSION"]
MAX_BUNDLE_TARGETS: int = _CFG["MAX_BUNDLE_TARGETS"]
IMPORT_FORMATS: dict[str, int] = dict(_CFG["IMPORT_FORMATS"])

REQUEST_ID = re.compile(r"^[0-9a-f]{12}$")


# ---------------------------------------------------------------------- export
def _exported(value: Any) -> str:
    """A credential as an export carries it: one that references a variable as written, a literal one blank."""
    return value if isinstance(value, str) and VARIABLE.search(value) else ""


def _exported_auth(auth: dict[str, Any]) -> dict[str, Any]:
    field = SECRET_FIELDS.get(auth.get("type"))
    return {"type": "none"} if field is None else {**auth, field: _exported(auth.get(field))}


def _exported_header(name: Any, value: Any) -> Any:
    credential = isinstance(name, str) and name.strip().lower() in CREDENTIAL_HEADERS
    return _exported(value) if credential else value


def export_bundle(
    targets: list[dict[str, Any]], requests: list[dict[str, Any]], settings: dict[str, Any], now: int | None = None
) -> dict[str, Any]:
    """
    The configuration as an export document: the targets, the saved requests of the targets and of the direct
    scope, the history limit. Auth secrets, secret variable values and credential header values are blank; one that
    references a variable is kept.
    """
    scopes = {DIRECT_TARGET_ID, *(target["id"] for target in targets)}
    return {
        "format": BUNDLE_FORMAT,
        "version": BUNDLE_VERSION,
        "exportedAt": now_ms() if now is None else now,
        "settings": {"historyLimit": settings["historyLimit"]},
        "targets": [
            {
                **{field: target[field] for field in ("id", "name", "baseUrl")},
                "auth": _exported_auth(target["auth"]),
                "headers": {name: _exported_header(name, value) for name, value in target["headers"].items()},
                "variables": dict(target["variables"]),
                "secrets": dict.fromkeys(target["secrets"], ""),
                "allowedHosts": list(target["allowedHosts"]),
                **{field: target[field] for field in ("allowMutations", "allowPrivate", "timeoutMs")},
            }
            for target in targets
        ],
        "requests": [
            {
                **{field: request[field] for field in ("id", "targetId", "name", "method", "path", "query")},
                "headers": [
                    {**row, "value": _exported_header(row.get("key"), row.get("value"))}
                    for row in request["headers"]
                    if isinstance(row, dict)
                ],
                "auth": _exported_auth(request["auth"]),
                **{field: request[field] for field in ("bodyMode", "body", "form", "captures")},
            }
            for request in requests
            if request["targetId"] in scopes
        ],
    }


# ---------------------------------------------------------------------- import
@dataclass
class ImportPlan:
    """
    The state of both stores after an import and what the import does. ``history_limit``: the file's history limit
    when it is valid.
    """

    targets: list[dict[str, Any]]
    requests: list[dict[str, Any]]
    result: dict[str, Any]
    history_limit: int | None = None


def _checked_format(raw: Any) -> dict[str, Any]:
    """The document when its format marker and version are ones an import reads."""
    marker = raw.get("format") if isinstance(raw, dict) else None
    if not isinstance(marker, str) or marker not in IMPORT_FORMATS:
        raise StoreError(f"not a {BUNDLE_FORMAT} export file")
    version = raw.get("version")
    if isinstance(version, bool) or not isinstance(version, int | float) or version > IMPORT_FORMATS[marker]:
        raise StoreError(f"unsupported export version {version}")
    return raw


def _items(value: Any) -> list[dict[str, Any]]:
    """The entries of a list of the document; an entry that is not an object reads as an empty one."""
    return [entry if isinstance(entry, dict) else {} for entry in value] if isinstance(value, list) else []


def _imported_target(
    item: dict[str, Any], name: str, taken: list[str], previous: dict[str, Any] | None
) -> dict[str, Any]:
    """
    A target of the document, over the target it overwrites. A blank secret takes the stored one: the auth secret
    when the type is unchanged, a secret variable and a fixed header when the name is. Without a stored value the
    auth secret and the secret variable stay blank, the fixed header is left out.
    """
    payload = {
        "name": name,
        **{field: item[field] for field in ("baseUrl", "auth", "timeoutMs") if item.get(field) is not None},
        **{field: item.get(field) for field in ("headers", "variables", "secrets", "allowedHosts")},
        "allowMutations": item.get("allowMutations") is True,
        "allowPrivate": item.get("allowPrivate") is True,
    }
    try:
        built = build_target(payload, taken, previous, allow_missing=True)
    except StoreError as exc:
        raise StoreError(f"target '{name}': {exc}") from exc
    kept = {header.lower(): value for header, value in (previous or {}).get("headers", {}).items()}
    filled = {header: value or kept.get(header.lower(), "") for header, value in built["headers"].items()}
    built["headers"] = {header: value for header, value in filled.items() if value}
    return built


def plan_import(raw: Any, targets: list[dict[str, Any]], requests: list[dict[str, Any]], conflict: str) -> ImportPlan:
    """
    Validate an export document against the current configuration and compute the state an import leaves; nothing
    is written. Targets match by name without regard to case; the requests without a target form one more unit.
    ``overwrite`` replaces a matched target's settings and its request list; ``skip`` leaves a matched target and
    its requests as they are. Raises :class:`StoreError` when the document or one of its entries is invalid.
    """
    bundle = _checked_format(raw)
    file_targets, file_requests = _items(bundle.get("targets")), _items(bundle.get("requests"))
    if len(file_targets) > MAX_BUNDLE_TARGETS:
        raise StoreError(f"at most {MAX_BUNDLE_TARGETS} targets per file")
    result: dict[str, Any] = {
        "conflicts": [],
        "created": [],
        "overwritten": [],
        "skipped": [],
        "needAuth": [],
        "requests": 0,
    }
    planned = list(targets)
    # File target id -> id of the target that receives its requests; absent for a skipped target.
    receiving: dict[str, str] = {}
    replaced: set[str] = set()
    seen: set[str] = set()
    for item in file_targets:
        name = item["name"].strip() if isinstance(item.get("name"), str) else ""
        if not name:
            raise StoreError("a target in the file has no name")
        if name.lower() in seen:
            raise StoreError(f"the file lists target '{name}' twice")
        seen.add(name.lower())
        index = next((i for i, target in enumerate(planned) if target["name"].lower() == name.lower()), None)
        previous = None if index is None else planned[index]
        if previous is not None:
            result["conflicts"].append(previous["name"])
            if conflict == "skip":
                result["skipped"].append(previous["name"])
                continue
        taken = [target["name"] for target in planned if target is not previous]
        built = _imported_target(item, name, taken, previous)
        if index is None:
            planned.append(built)
            result["created"].append(built["name"])
        else:
            planned[index] = built
            replaced.add(built["id"])
            result["overwritten"].append(built["name"])
        if auth_missing(built["auth"]) or missing_secrets(built):
            result["needAuth"].append(built["name"])
        if isinstance(item.get("id"), str) and item["id"]:
            receiving[item["id"]] = built["id"]

    # Requests without a target: one unit that follows the same choice.
    file_direct = any(item.get("targetId") == DIRECT_TARGET_ID for item in file_requests)
    have_direct = any(request["targetId"] == DIRECT_TARGET_ID for request in requests)
    if file_direct and have_direct:
        result["conflicts"].append(DIRECT_TARGET_ID)
    if file_direct and not (have_direct and conflict == "skip"):
        receiving[DIRECT_TARGET_ID] = DIRECT_TARGET_ID
        if have_direct:
            replaced.add(DIRECT_TARGET_ID)

    stored = [request for request in requests if request["targetId"] not in replaced]
    used = {request["id"] for request in stored}
    held = Counter(request["targetId"] for request in stored)
    for item in file_requests:
        target_id = receiving.get(item["targetId"]) if isinstance(item.get("targetId"), str) else None
        if target_id is None:
            continue
        held[target_id] += 1
        if held[target_id] > MAX_REQUESTS_PER_TARGET:
            raise StoreError(f"at most {MAX_REQUESTS_PER_TARGET} requests per target")
        # The file's id is kept while it is free: the history stays linked on a re-import.
        own = item.get("id")
        free = isinstance(own, str) and REQUEST_ID.match(own) is not None and own not in used
        request_id = own if free else secrets.token_hex(6)
        try:
            built = build_request(target_id, item, request_id)
        except StoreError as exc:
            title = next((text for text in (item.get("name"), item.get("path")) if isinstance(text, str) and text), "")
            raise StoreError(f"request '{title}': {exc}") from exc
        used.add(request_id)
        stored.append(built)
        result["requests"] += 1

    settings = bundle.get("settings")
    limit = settings.get("historyLimit") if isinstance(settings, dict) else None
    valid = isinstance(limit, int) and not isinstance(limit, bool) and MIN_HISTORY_LIMIT <= limit <= MAX_HISTORY_LIMIT
    return ImportPlan(planned, stored, result, limit if valid else None)
