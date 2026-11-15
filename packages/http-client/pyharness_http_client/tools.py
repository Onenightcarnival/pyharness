"""
The ``http_*`` LangChain tools; every result is text for the model.

| tool             | contract                                                                             |
|------------------|--------------------------------------------------------------------------------------|
| ``http_targets`` | a table of the targets: name, base URL, auth type, mutations, variable names, extra hosts |
| ``http_request`` | one request through the engine; a method other than GET / HEAD / OPTIONS needs the target's |
|                  | mutation switch and ``confirm=true``                                                  |
| ``http_history`` | the recent exchanges of one target or of every target; requests without a target are left out |

Secrets never reach a result: the engine masks them and the target table carries the auth type only.
"""

from __future__ import annotations

from datetime import UTC, datetime
from string import Template
from typing import Any, Protocol

from langchain_core.tools import tool
from pydantic import Field

from pyharness import package_prompts, package_toml

from .engine import HttpEngine, PolicyError, SendOptions, human_bytes, truncate
from .protocol import DIRECT_TARGET_ID, SAFE_METHODS, is_method
from .store import HistoryStore, TargetStore, summarize

_CFG = package_toml(__file__)["tools"]
PROMPTS = package_prompts(__file__)["tools"]
TOOL_BODY_BYTES: int = _CFG["TOOL_BODY_BYTES"]
TOOL_HISTORY_MAX: int = _CFG["TOOL_HISTORY_MAX"]
TOOL_HISTORY_DEFAULT: int = _CFG["TOOL_HISTORY_DEFAULT"]
REQUEST_PREVIEW_BYTES = 2048
RESPONSE_PREVIEW_BYTES = 200
TABLE_HEAD = "name | base URL | auth | mutations | variables | extra hosts\n--- | --- | --- | --- | --- | ---"


class Host(Protocol):
    """The service, as the tools use it."""

    store: TargetStore
    history: HistoryStore
    engine: HttpEngine


def to_output(exchange: dict[str, Any]) -> dict[str, Any]:
    """Model-facing projection of an exchange."""
    response = exchange.get("response")
    if "error" in exchange or response is None:
        return {"ok": False, "error": exchange.get("error") or "no response", "url": exchange["request"]["url"] or None}
    body, cut = truncate(response["body"], TOOL_BODY_BYTES)
    fields = ("status", "statusText", "headers", "contentType", "bodyBytes", "binary", "durationMs", "redirects")
    return {
        "ok": True,
        "url": exchange["request"]["url"],
        **{field: response[field] for field in fields},
        "body": body,
        "bodyTruncated": response["bodyTruncated"] or cut,
    }


def render_exchange(method: str, value: dict[str, Any]) -> str:
    """The text of an exchange output."""
    if not value["ok"]:
        where = f" ({method} {value['url']})" if value.get("url") else ""
        return f"request failed{where}: {value.get('error') or 'unknown error'}"
    lines = [f"{method} {value['url']} → {value['status']} {value['statusText']} ({value['durationMs']} ms)"]
    if value["redirects"]:
        lines.append(f"redirected via: {' → '.join(value['redirects'])}")
    cut = " (truncated)" if value["bodyTruncated"] else ""
    lines.append(f"{value['contentType'] or 'no content-type'} · {human_bytes(value['bodyBytes'])}{cut}")
    if value["binary"]:
        lines.append("[binary body omitted]")
    elif value["body"]:
        lines += ["", value["body"]]
    return "\n".join(lines)


def _target_row(target: dict[str, Any]) -> str:
    mutations = "allowed (confirm required)" if target["allowMutations"] else "GET/HEAD/OPTIONS only"
    variables = " ".join(f"{{{{{name}}}}}" for name in target["variables"]) or "-"
    hosts = ", ".join(target["allowedHosts"]) or "-"
    return f"{target['name']} | {target['baseUrl']} | {target['auth']['type']} | {mutations} | {variables} | {hosts}"


def _history_row(entry: dict[str, Any]) -> str:
    request, response = entry["request"], entry.get("response")
    stamp = datetime.fromtimestamp(entry["at"] / 1000, UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    if "error" in entry or response is None:
        outcome = f"error: {entry.get('error') or 'no response'}"
    else:
        outcome = f"{response['status']} ({response['durationMs']} ms)"
    row = f"{stamp} [{entry['source']}] {entry['targetName']}: {request['method']} {request['url']} → {outcome}"
    if request["body"]:
        row += f"\n    request body: {truncate(request['body'], REQUEST_PREVIEW_BYTES)[0]}"
    if response is not None and response["body"]:
        row += f"\n    {truncate(' '.join(response['body'].split()), RESPONSE_PREVIEW_BYTES)[0]}"
    return row


def build_tools(service: Host) -> list[Any]:
    @tool("http_targets", description=PROMPTS["http_targets"])
    def http_targets() -> str:
        targets = [summarize(target) for target in service.store.list()]
        if not targets:
            return PROMPTS["no_targets"]
        return "\n".join([TABLE_HEAD, *(_target_row(target) for target in targets)])

    request_description = Template(PROMPTS["http_request"]).substitute(body_kib=TOOL_BODY_BYTES // 1024)

    @tool("http_request", description=request_description)
    async def http_request(
        target: str = Field(description="Target name (or id) from http_targets."),
        method: str = Field(description="GET, POST, PUT, PATCH, DELETE, HEAD or OPTIONS."),
        path: str = Field(
            description='Path below the base URL, e.g. "/users/42?expand=1"; an absolute https URL is accepted on '
            "allowed hosts."
        ),
        query: dict[str, Any] | None = Field(None, description="Query parameters appended to the URL (string values)."),
        headers: dict[str, Any] | None = Field(
            None,
            description="Extra request headers (string values); content-type defaults to application/json for a JSON "
            "body.",
        ),
        body: str | None = Field(
            None, description="Raw request body for POST / PUT / PATCH / DELETE (JSON as a string)."
        ),
        confirm: bool = Field(
            False,
            description="Required true for POST / PUT / PATCH / DELETE; set only after the user explicitly confirmed "
            "this exact request.",
        ),
    ) -> str:
        verb = str(method or "GET").upper()
        if not is_method(verb):
            return render_exchange(verb, {"ok": False, "error": f"unsupported method '{method}'"})
        try:
            found = service.engine.target(target)
            if verb not in SAFE_METHODS:
                if not found["allowMutations"]:
                    raise PolicyError(Template(PROMPTS["mutations_off"]).substitute(name=found["name"]))
                if confirm is not True:
                    raise PolicyError(PROMPTS["confirm_required"])
            composed = {"method": verb, "path": path, "query": query, "headers": headers, "body": body}
            options = SendOptions(source="agent", max_body_bytes=TOOL_BODY_BYTES)
            exchange = await service.engine.send(found["id"], composed, options)
        except PolicyError as exc:
            return render_exchange(verb, {"ok": False, "error": " ".join(str(exc).split())})
        return render_exchange(verb, to_output(exchange))

    @tool("http_history", description=PROMPTS["http_history"])
    def http_history(
        target: str | None = Field(None, description="Target name (or id); omit for every target."),
        limit: int | None = Field(None, description=f"Entries to return (default 20, cap {TOOL_HISTORY_MAX})."),
    ) -> str:
        count = min(TOOL_HISTORY_MAX, max(1, limit or TOOL_HISTORY_DEFAULT))
        if target:
            found = service.store.find(target)
            if found is None:
                return f"history failed: target '{target}' not found"
            entries = service.history.list(found["id"], count)
        else:
            # Requests the user sent without a target stay out of the agent's view.
            everything = service.history.list(None, 1_000_000_000)
            entries = [entry for entry in everything if entry["targetId"] != DIRECT_TARGET_ID][:count]
        return "\n".join(_history_row(entry) for entry in entries) or PROMPTS["no_history"]

    return [http_targets, http_request, http_history]
