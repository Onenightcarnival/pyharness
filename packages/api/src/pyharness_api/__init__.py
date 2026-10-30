"""REST and SSE API over ``ctx.agents``, under ``/api`` on ``ctx.http``.

| method | path                         | body                          | response                                    |
|--------|------------------------------|-------------------------------|---------------------------------------------|
| GET    | ``/health``                  |                               | generation, restart state, model, workspace |
| GET    | ``/plugins``                 |                               | loader entries, installed bundles           |
| GET    | ``/sessions``                |                               | sessions                                    |
| POST   | ``/sessions``                | ``{"title"?}``                | session                                     |
| GET    | ``/sessions/{id}``           |                               | session, busy, messages, pending approvals  |
| POST   | ``/sessions/{id}/messages``  | ``{"content"}``               | SSE run events                              |
| POST   | ``/sessions/{id}/approvals`` | ``{"decisions": [decision]}`` | SSE run events                              |
| POST   | ``/sessions/{id}/cancel``    |                               | ``{"cancelled"}``                           |
| DELETE | ``/sessions/{id}``           |                               | ``{"deleted"}``                             |
| GET    | ``/sessions/{id}/stream``    |                               | SSE of the running turn; 204 when idle      |
| PUT    | ``/sessions/{id}/model``     | ``{"model"}``                 | select ``route:model`` for the session      |
| GET    | ``/models``                  |                               | selector directory: routes, models, default |
| GET    | ``/settings/models``         |                               | routes with credential state, catalog       |
| PUT    | ``/settings/models``         | ``{"default"}``               | default model for new sessions              |
| PUT    | ``/settings/models/{route}`` | ``route settings``            | create or edit a route; applies at once     |
| DELETE | ``/settings/models/{route}`` |                               | remove a route and its stored credential    |
| POST   | ``/settings/models/{route}/discover`` | ``route settings``   | model ids served by the endpoint            |
| POST   | ``/settings/models/{route}/test``     | ``route settings``   | one short completion with ``model``         |

| status | condition                                 |
|--------|-------------------------------------------|
| 404    | unknown session                           |
| 409    | running turn, or approvals pending/absent |
| 503    | restart pending (``Retry-After: 2``)      |

``decision``: ``{"type": "approve"}`` or ``{"type": "reject"}``.

``route settings``: ``{"type"?, "title"?, "protocol"?, "base_url"?, "api_key"?, "models"?, "options"?, "model"?}``.
A typed ``api_key`` is stored in the profile credential store under ``<ROUTE>_API_KEY`` and referenced from the
configuration; ``""`` deletes it; absent keeps it. Values are never returned. Saved settings apply to the next
model request without a restart.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, HTTPException, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

name = "pyharness-api"
inject = ["http", "agents", "llm"]


class Config(BaseModel):
    prefix: str = "/api"
    llm_entry: str = Field("llm", description="Entry id of the model registry the settings page edits.")


class NewSession(BaseModel):
    title: str | None = None
    model: str | None = Field(None, description="route:model for this session; null: the default.")


class NewMessage(BaseModel):
    content: str = Field(..., min_length=1)


class Approvals(BaseModel):
    decisions: list[dict[str, Any]]


class RouteSettings(BaseModel):
    """Fields of one model route. ``None`` keeps the saved value; ``api_key`` '' clears the stored credential."""

    type: str | None = None
    title: str | None = None
    protocol: str | None = Field(None, description="Custom endpoints: openai-chat, openai-responses, anthropic-messages.")
    base_url: str | None = None
    api_key: str | None = None
    models: list[dict[str, Any]] | None = None
    options: dict[str, Any] | None = None
    model: str | None = Field(None, description="Model id for /test.")


class DefaultModel(BaseModel):
    default: str | None = Field(None, description="route:model for new sessions; null clears it.")


class SessionModel(BaseModel):
    model: str | None = Field(None, description="route:model; null returns to the default.")


def _sse(events: AsyncIterator[dict[str, Any]]) -> StreamingResponse:
    async def body() -> AsyncIterator[bytes]:
        async for event in events:
            yield f"data: {json.dumps(event, ensure_ascii=False, default=str)}\n\n".encode()

    return StreamingResponse(body(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})


def build_router(ctx: Any) -> APIRouter:
    from pyharness_agent import RestartPending, SessionBusy

    router = APIRouter()
    agents = ctx.agents

    async def require(session_id: str) -> dict[str, Any]:
        session = await agents.get_session(session_id)
        if session is None:
            raise HTTPException(404, f"no session {session_id}")
        return session

    @router.get("/health")
    async def health() -> dict[str, Any]:
        lifecycle = ctx.lifecycle
        profile = ctx.get("profile", None)
        llm = ctx.get("llm", None)
        workspace = ctx.get("workspace", None)
        return {
            "ok": True,
            "generation": lifecycle.generation,
            "supervised": lifecycle.supervised,
            "restart_pending": lifecycle.restart_pending,
            "profile": profile.name if profile is not None else None,
            "model": getattr(llm, "default", None) if llm is not None else None,
            "workspace": {"name": workspace.root.name or str(workspace.root), "path": str(workspace.root)}
            if workspace is not None
            else None,
        }

    @router.get("/plugins")
    async def plugins() -> dict[str, Any]:
        profile = ctx.get("profile", None)
        return {
            "entries": ctx.loader.snapshot(),
            "bundles": profile.installed_bundles() if profile is not None else [],
        }

    @router.get("/sessions")
    async def list_sessions() -> list[dict[str, Any]]:
        return await agents.list_sessions()

    @router.post("/sessions")
    async def create_session(body: NewSession | None = None) -> dict[str, Any]:
        return await agents.create_session(title=body.title if body else None, model=body.model if body else None)

    @router.put("/sessions/{session_id}/model")
    async def set_session_model(session_id: str, body: SessionModel) -> dict[str, Any]:
        record = await agents.set_model(session_id, body.model)
        if record is None:
            raise HTTPException(404, f"no session {session_id}")
        return record

    @router.get("/sessions/{session_id}")
    async def get_session(session_id: str) -> dict[str, Any]:
        session = await require(session_id)
        return {
            **session,
            "busy": agents.busy(session_id),
            "messages": await agents.messages(session_id),
            "pending": await agents.pending(session_id),
        }

    @router.post("/sessions/{session_id}/messages")
    async def post_message(session_id: str, body: NewMessage) -> StreamingResponse:
        await require(session_id)
        if await agents.pending(session_id):
            raise HTTPException(409, "the session is waiting for approval decisions")
        try:
            handle = agents.start_run(session_id, body.content)
        except SessionBusy as exc:
            raise HTTPException(409, str(exc)) from None
        except RestartPending as exc:
            raise HTTPException(503, str(exc), headers={"Retry-After": "2"}) from None
        return _sse(handle.subscribe())

    @router.post("/sessions/{session_id}/approvals")
    async def post_approvals(session_id: str, body: Approvals) -> StreamingResponse:
        await require(session_id)
        if not await agents.pending(session_id):
            raise HTTPException(409, "nothing is waiting for approval")
        try:
            handle = agents.start_run(session_id, decisions=body.decisions)
        except SessionBusy as exc:
            raise HTTPException(409, str(exc)) from None
        except RestartPending as exc:
            raise HTTPException(503, str(exc), headers={"Retry-After": "2"}) from None
        return _sse(handle.subscribe())

    @router.post("/sessions/{session_id}/cancel")
    async def cancel(session_id: str) -> dict[str, Any]:
        await require(session_id)
        return {"cancelled": await agents.cancel(session_id)}

    @router.delete("/sessions/{session_id}")
    async def delete(session_id: str) -> dict[str, Any]:
        try:
            deleted = await agents.delete_session(session_id)
        except SessionBusy as exc:
            raise HTTPException(409, str(exc)) from None
        if not deleted:
            raise HTTPException(404, f"no session {session_id}")
        return {"deleted": True}

    @router.get("/sessions/{session_id}/stream", response_model=None)
    async def attach(session_id: str) -> Response:
        await require(session_id)
        handle = agents.current_run(session_id)
        if handle is None or handle.done:
            return Response(status_code=204)
        return _sse(handle.subscribe())

    return router


def build_settings_router(ctx: Any, llm_entry: str) -> APIRouter:
    from pyharness_llm import PROTOCOLS, LLMConfig, LLMConfigError, ProviderConfig, split_spec, type_info

    from pyharness import manage
    from pyharness.credentials import reference_for

    router = APIRouter()

    def llm() -> Any:
        service = ctx.get("llm", None)
        if service is None:
            raise HTTPException(503, "model registry (ctx.llm) unavailable")
        return service

    def profile() -> Any:
        profile = ctx.get("profile", None)
        if profile is None:
            raise HTTPException(409, "no profile: model settings are read-only in this harness")
        return profile

    async def persist(service: Any) -> None:
        """Write the live llm configuration (without secrets) to the profile patch; no restart needed."""
        data = service.config.model_dump(mode="json", exclude_none=True, exclude_defaults=True)
        for route in data.get("providers", {}).values():
            route.pop("api_key", None)
        await manage.set_entry_config(profile(), llm_entry, data, merge=False, preflight=False)

    def view(service: Any) -> dict[str, Any]:
        lifecycle = ctx.lifecycle
        return {
            **service.describe(),
            "protocols": [{"id": k, "title": v["title"], "type": v["type"]} for k, v in PROTOCOLS.items()],
            "entry": llm_entry,
            "generation": lifecycle.generation,
            "editable": ctx.get("profile", None) is not None,
        }

    @router.get("/models")
    async def model_directory() -> dict[str, Any]:
        return llm().directory()

    @router.get("/settings/models")
    async def get_model_settings() -> dict[str, Any]:
        return view(llm())

    @router.put("/settings/models")
    async def put_default_model(body: DefaultModel) -> dict[str, Any]:
        service = llm()
        route, model = split_spec(body.default)
        if body.default and (not route or not model):
            raise HTTPException(422, "default must be route:model")
        service.update(default=body.default or None)
        await persist(service)
        return view(service)

    @router.put("/settings/models/{route}")
    async def put_route(route: str, body: RouteSettings) -> dict[str, Any]:
        service = llm()
        store = profile().credentials
        current = service.config.providers.get(route)
        data = current.model_dump(mode="python", exclude_none=True) if current is not None else {}
        data.pop("api_key", None)
        for field in ("type", "title", "protocol", "base_url", "models", "options"):
            value = getattr(body, field)
            if value is not None:
                data[field] = value or None if field in ("title", "base_url") else value
        if body.protocol is not None and body.protocol:
            data["type"] = PROTOCOLS[body.protocol]["type"]
        kind = PROTOCOLS[data["protocol"]]["type"] if data.get("protocol") else (data.get("type") or route)
        info = type_info(kind)
        if info["package"] is None and kind not in service.providers():
            raise HTTPException(422, f"unknown provider type {kind!r}")
        if data.get("protocol") and not data.get("base_url"):
            raise HTTPException(422, "a custom endpoint needs base_url")
        reference = data.get("api_key_env") or (info["env"] if route == kind else reference_for(route)) or reference_for(route)
        plain = current.api_key if current is not None else None  # legacy: key written in the configuration
        if body.api_key:
            try:
                store.set(reference, body.api_key)
            except ValueError as exc:
                raise HTTPException(422, str(exc)) from None
            data["api_key_env"] = reference
        elif body.api_key == "":
            store.delete(reference)
        elif plain and not store.describe(reference)["configured"]:
            store.set(reference, plain)  # migrate the plain key into the store; the configuration keeps the reference
            data["api_key_env"] = reference
        try:
            cfg = ProviderConfig.model_validate(data)
            providers = {
                **{k: v.model_dump(mode="python", exclude_none=True) for k, v in service.config.providers.items()},
                route: cfg.model_dump(mode="python", exclude_none=True),
            }
            default = service.config.default
            if not default or (cfg.models and split_spec(default)[0] not in providers):
                default = f"{route}:{cfg.models[0].id}" if cfg.models else default
            service.update(providers=providers, default=default)
        except (ValueError, LLMConfigError) as exc:
            raise HTTPException(422, str(exc)) from None
        await persist(service)
        return {"route": service.describe_route(route), **view(service)}

    @router.delete("/settings/models/{route}")
    async def delete_route(route: str) -> dict[str, Any]:
        service = llm()
        if route not in service.config.providers:
            raise HTTPException(404, f"no route {route!r}")
        cfg = service.config.providers[route]
        providers = {k: v.model_dump(mode="python", exclude_none=True) for k, v in service.config.providers.items() if k != route}
        default = service.config.default
        if default and split_spec(default)[0] == route:
            default = next((f"{r}:{v['models'][0]['id']}" for r, v in providers.items() if v.get("models")), "echo:echo")
        service.update(providers=providers, default=default)
        if cfg.api_key_env:
            profile().credentials.delete(cfg.api_key_env)
        await persist(service)
        return view(service)

    @router.post("/settings/models/{route}/discover")
    async def discover_models(route: str, body: RouteSettings) -> dict[str, Any]:
        overrides = {k: v for k, v in (("base_url", body.base_url), ("api_key", body.api_key), ("protocol", body.protocol)) if v}
        kind = PROTOCOLS[body.protocol]["type"] if body.protocol else body.type
        try:
            return {"ok": True, **await llm().list_models(route, kind, **overrides)}
        except LLMConfigError as exc:
            return {"ok": False, "error": str(exc), "models": []}

    @router.post("/settings/models/{route}/test")
    async def test_route(route: str, body: RouteSettings) -> dict[str, Any]:
        service = llm()
        model = (body.model or "").strip()
        if not model:
            raise HTTPException(422, "model is required")
        overrides: dict[str, Any] = {k: v for k, v in (("base_url", body.base_url), ("api_key", body.api_key)) if v}
        if body.protocol:
            overrides.update(PROTOCOLS[body.protocol]["options"])
        cfg = service.config.providers.get(route)
        if cfg is None and (body.type or body.protocol):
            kind = PROTOCOLS[body.protocol]["type"] if body.protocol else body.type
            overrides["type"] = kind
        try:
            kind = overrides.pop("type", None)
            if kind and cfg is None:
                # Unsaved route: resolve through a temporary configuration.
                temp = LLMConfig.model_validate(
                    {
                        **service.config.model_dump(mode="python"),
                        "providers": {
                            **{k: v.model_dump(mode="python", exclude_none=True) for k, v in service.config.providers.items()},
                            route: {"type": kind},
                        },
                    }
                )
                saved = service.config
                service.config = temp
                try:
                    return await service.probe(route, model, **overrides)
                finally:
                    service.config = saved
                    service.invalidate()
            return await service.probe(route, model, **overrides)
        except LLMConfigError as exc:
            return {"ok": False, "error": str(exc)}

    return router


def apply(ctx: Any, config: Config) -> None:
    ctx.http.include_router(build_router(ctx), prefix=config.prefix, tags=["pyharness"])
    ctx.http.include_router(build_settings_router(ctx, config.llm_entry), prefix=config.prefix, tags=["pyharness"])
