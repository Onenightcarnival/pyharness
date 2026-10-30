"""REST and SSE API over ``ctx.agents``, under ``/api`` on ``ctx.http``.

| method | path                         | body                          | response                                    |
|--------|------------------------------|-------------------------------|---------------------------------------------|
| GET    | ``/health``                  |                               | generation, restart state, model, workspace |
| GET    | ``/plugins``                 |                               | loader entries, installed bundles           |
| GET    | ``/sessions``                |                               | sessions                                    |
| POST   | ``/sessions``                | ``{"title"?, "model"?, "workspace"?, "mode"?, "preset"?}`` | session        |
| GET    | ``/sessions/{id}``           |                               | session, busy, messages, pending approvals  |
| POST   | ``/sessions/{id}/messages``  | ``{"content", "images"?}``    | SSE run events; images: data URLs           |
| POST   | ``/sessions/{id}/approvals`` | ``{"decisions": [decision]}`` | SSE run events                              |
| POST   | ``/sessions/{id}/cancel``    |                               | ``{"cancelled"}``                           |
| DELETE | ``/sessions/{id}``           |                               | ``{"deleted"}``                             |
| GET    | ``/sessions/{id}/stream``    |                               | SSE of the running turn; 204 when idle      |
| PUT    | ``/sessions/{id}``           | ``{"title"}``                 | rename the session                          |
| PUT    | ``/sessions/{id}/model``     | ``{"model"}``                 | select ``route:model`` for the session      |
| PUT    | ``/sessions/{id}/mode``      | ``{"mode"}``                  | permission mode; next run                   |
| PUT    | ``/sessions/{id}/preset``    | ``{"preset"}``                | agent preset; next run                      |
| GET    | ``/agent``                   |                               | presets, modes, defaults for new sessions   |
| PUT    | ``/settings/agent``          | ``{"default_preset"?, "default_mode"?}`` | defaults for new sessions; persisted |
| GET    | ``/workspaces``              |                               | default and recent workspaces, picker kind  |
| POST   | ``/workspaces/pick``         | ``{"path"?: prompt}``         | OS folder dialog on this machine; null = cancelled |
| POST   | ``/workspaces``              | ``{"path"}``                  | validate and remember a workspace           |
| PUT    | ``/workspaces``              | ``{"path", "name"}``          | display name of a workspace                 |
| DELETE | ``/workspaces?path=``        |                               | forget a workspace                          |
| POST   | ``/workspaces/browse``       | ``{"path"?}``                 | one directory level for the picker          |
| GET    | ``/workspaces/files``        | ``?path=&root=``              | directory entries inside a workspace        |
| GET    | ``/workspaces/file``         | ``?path=&root=&limit=``       | text of a file inside a workspace           |
| GET    | ``/workspaces/file/raw``     | ``?path=&root=``              | bytes of a file inside a workspace (images) |
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
| 422    | images sent to a model without image input |
| 503    | restart pending (``Retry-After: 2``)      |

``decision``: ``{"type": "approve"}`` or ``{"type": "reject"}``.

``route settings``: ``{"type"?, "title"?, "protocol"?, "base_url"?, "api_key"?, "models"?, "options"?, "model"?}``.
A typed ``api_key`` is stored in the profile credential store under ``<ROUTE>_API_KEY`` and referenced from the
configuration; ``""`` deletes it; absent keeps it. Values are never returned. Saved settings apply to the next
model request without a restart.
"""

from __future__ import annotations

import json
import mimetypes
import re
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, HTTPException, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, field_validator, model_validator

name = "pyharness-api"
inject = ["http", "agents", "llm"]


class Config(BaseModel):
    prefix: str = "/api"
    llm_entry: str = Field("llm", description="Entry id of the model registry the settings page edits.")


class NewSession(BaseModel):
    title: str | None = None
    model: str | None = Field(None, description="route:model for this session; null: the default.")
    workspace: str | None = Field(None, description="Absolute workspace directory; null: the default workspace.")
    mode: str | None = Field(None, description="Permission mode; null: the default.")
    preset: str | None = Field(None, description="Agent preset; null: the default.")


class SessionMode(BaseModel):
    mode: str


class SessionPreset(BaseModel):
    preset: str


class WorkspacePath(BaseModel):
    path: str | None = None
    name: str | None = None


class SessionTitle(BaseModel):
    title: str | None = None


class AgentDefaults(BaseModel):
    default_preset: str | None = None
    default_mode: str | None = None


IMAGE_DATA_URL = re.compile(r"^data:image/(png|jpeg|gif|webp);base64,([A-Za-z0-9+/=]+)$")
MAX_IMAGES = 8
MAX_IMAGE_BYTES = 8 * 1024 * 1024


class NewMessage(BaseModel):
    content: str = Field("", description="Text; may be empty when images are attached.")
    images: list[str] = Field(default_factory=list, description="Image data URLs (png, jpeg, gif, webp); at most 8, 8 MB each.")

    @field_validator("images")
    @classmethod
    def _images(cls, value: list[str]) -> list[str]:
        if len(value) > MAX_IMAGES:
            raise ValueError(f"at most {MAX_IMAGES} images per message")
        for url in value:
            match = IMAGE_DATA_URL.match(url)
            if not match:
                raise ValueError("images must be data URLs of type image/png, image/jpeg, image/gif or image/webp")
            if len(match.group(2)) * 3 // 4 > MAX_IMAGE_BYTES:
                raise ValueError(f"an image is larger than {MAX_IMAGE_BYTES // (1024 * 1024)} MB")
        return value

    @model_validator(mode="after")
    def _not_empty(self) -> NewMessage:
        if not self.content.strip() and not self.images:
            raise ValueError("a message needs text or images")
        return self


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
        body = body or NewSession()
        try:
            return await agents.create_session(
                title=body.title, model=body.model, workspace=body.workspace, mode=body.mode, preset=body.preset
            )
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from None

    @router.put("/sessions/{session_id}")
    async def rename_session(session_id: str, body: SessionTitle) -> dict[str, Any]:
        record = await agents.set_title(session_id, body.title)
        if record is None:
            raise HTTPException(404, f"no session {session_id}")
        return record

    @router.put("/sessions/{session_id}/model")
    async def set_session_model(session_id: str, body: SessionModel) -> dict[str, Any]:
        record = await agents.set_model(session_id, body.model)
        if record is None:
            raise HTTPException(404, f"no session {session_id}")
        return record

    @router.put("/sessions/{session_id}/mode")
    async def set_session_mode(session_id: str, body: SessionMode) -> dict[str, Any]:
        try:
            record = await agents.set_mode(session_id, body.mode)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from None
        if record is None:
            raise HTTPException(404, f"no session {session_id}")
        return record

    @router.put("/sessions/{session_id}/preset")
    async def set_session_preset(session_id: str, body: SessionPreset) -> dict[str, Any]:
        try:
            record = await agents.set_preset(session_id, body.preset)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from None
        if record is None:
            raise HTTPException(404, f"no session {session_id}")
        return record

    @router.get("/agent")
    async def agent_options() -> dict[str, Any]:
        loop = ctx.get("agentLoop", None)
        if loop is None or not hasattr(loop, "presets"):
            return {"presets": [], "modes": [], "default_preset": None, "default_mode": None}
        return {
            "presets": loop.presets(),
            "modes": loop.modes(),
            "default_preset": loop.config.default_preset,
            "default_mode": loop.config.default_mode,
        }

    @router.get("/workspaces")
    async def list_workspaces() -> dict[str, Any]:
        workspaces = ctx.get("workspace", None)
        if workspaces is None or not hasattr(workspaces, "recent"):
            return {"default": None, "recent": []}
        return {"default": workspaces.default.describe(), "recent": await workspaces.recent(), "picker": workspaces.picker()}

    @router.post("/workspaces/pick")
    async def pick_workspace(body: WorkspacePath) -> dict[str, Any]:
        """Open the OS folder dialog on this machine; ``{"path": null}`` when cancelled."""
        workspaces = ctx.get("workspace", None)
        if workspaces is None or not hasattr(workspaces, "pick"):
            raise HTTPException(503, "workspace registry unavailable")
        try:
            chosen = await workspaces.pick(body.path or "Choose a workspace directory")
            if chosen is None:
                return {"path": None}
            return {"path": chosen, **(await workspaces.remember(chosen))}
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from None

    @router.post("/workspaces")
    async def add_workspace(body: WorkspacePath) -> dict[str, Any]:
        workspaces = ctx.get("workspace", None)
        if workspaces is None or not hasattr(workspaces, "remember"):
            raise HTTPException(503, "workspace registry unavailable")
        try:
            return await workspaces.remember(body.path)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from None

    @router.put("/workspaces")
    async def rename_workspace(body: WorkspacePath) -> dict[str, Any]:
        workspaces = ctx.get("workspace", None)
        if workspaces is None or not hasattr(workspaces, "rename"):
            raise HTTPException(503, "workspace registry unavailable")
        try:
            return await workspaces.rename(body.path, body.name)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from None

    @router.delete("/workspaces")
    async def forget_workspace(path: str) -> dict[str, Any]:
        workspaces = ctx.get("workspace", None)
        if workspaces is None or not hasattr(workspaces, "forget"):
            raise HTTPException(503, "workspace registry unavailable")
        return {"forgotten": await workspaces.forget(path)}

    @router.get("/workspaces/files")
    async def list_files(path: str = "/", root: str | None = None) -> dict[str, Any]:
        """Entries of a directory inside a workspace (``root``: its directory; default workspace when absent)."""
        workspaces = ctx.get("workspace", None)
        if workspaces is None or not hasattr(workspaces, "open"):
            raise HTTPException(503, "workspace registry unavailable")
        try:
            ws = workspaces.open(root)
            real = ws.resolve(path)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from None
        if not real.is_dir():
            raise HTTPException(404, f"{path} is not a directory")
        entries = []
        try:
            for item in sorted(real.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())):
                try:
                    stat = item.stat()
                except OSError:
                    continue
                virtual = "/" + item.relative_to(ws.root).as_posix()
                entries.append(
                    {
                        "name": item.name,
                        "path": virtual,
                        "dir": item.is_dir(),
                        "size": None if item.is_dir() else stat.st_size,
                        "hidden": item.name.startswith("."),
                        "mtime": stat.st_mtime,
                    }
                )
        except PermissionError as exc:
            raise HTTPException(403, str(exc)) from None
        return {"root": str(ws.root), "path": "/" + real.relative_to(ws.root).as_posix() if real != ws.root else "/", "entries": entries}

    @router.get("/workspaces/file")
    async def read_file(path: str, root: str | None = None, limit: int = 512 * 1024) -> dict[str, Any]:
        """Text of a file inside a workspace, up to ``limit`` bytes; binary files report ``binary``."""
        workspaces = ctx.get("workspace", None)
        if workspaces is None or not hasattr(workspaces, "open"):
            raise HTTPException(503, "workspace registry unavailable")
        try:
            ws = workspaces.open(root)
            real = ws.resolve(path)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from None
        if not real.is_file():
            raise HTTPException(404, f"{path} is not a file")
        size = real.stat().st_size
        with real.open("rb") as fh:
            data = fh.read(limit)
        try:
            text = data.decode("utf-8")
            binary = "\x00" in text
        except UnicodeDecodeError:
            text, binary = "", True
        return {"path": path, "size": size, "truncated": size > limit, "binary": binary, "text": "" if binary else text}

    @router.get("/workspaces/file/raw")
    async def read_file_raw(path: str, root: str | None = None) -> Response:
        """Bytes of a file inside a workspace (images for the preview), up to 20 MB, with a guessed content type."""
        workspaces = ctx.get("workspace", None)
        if workspaces is None or not hasattr(workspaces, "open"):
            raise HTTPException(503, "workspace registry unavailable")
        try:
            real = workspaces.open(root).resolve(path)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from None
        if not real.is_file():
            raise HTTPException(404, f"{path} is not a file")
        if real.stat().st_size > 20 * 1024 * 1024:
            raise HTTPException(413, f"{path} is larger than 20 MB")
        media = mimetypes.guess_type(real.name)[0] or "application/octet-stream"
        if media.startswith("text/html") or media.endswith("svg+xml"):
            media = "text/plain; charset=utf-8" if media.startswith("text/html") else "image/svg+xml"
        headers = {
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'",
        }
        return Response(real.read_bytes(), media_type=media, headers=headers)

    @router.post("/workspaces/browse")
    async def browse_workspaces(body: WorkspacePath) -> dict[str, Any]:
        workspaces = ctx.get("workspace", None)
        if workspaces is None or not hasattr(workspaces, "browse"):
            raise HTTPException(503, "workspace registry unavailable")
        try:
            return workspaces.browse(body.path)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from None

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
        session = await require(session_id)
        if await agents.pending(session_id):
            raise HTTPException(409, "the session is waiting for approval decisions")
        if body.images:
            llm = ctx.get("llm", None)
            spec = session.get("model") or (llm.default if llm is not None else None)
            if llm is not None and llm.accepts_images(spec) is False:
                raise HTTPException(
                    422, f"model {spec} does not accept image input; choose a model with image input or edit its input types in Settings"
                )
        try:
            handle = agents.start_run(session_id, body.content, images=body.images or None)
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

    @router.put("/settings/agent")
    async def put_agent_defaults(body: AgentDefaults) -> dict[str, Any]:
        loop = ctx.get("agentLoop", None)
        if loop is None or not hasattr(loop, "set_defaults"):
            raise HTTPException(503, "agent loop unavailable")
        try:
            defaults = loop.set_defaults(preset=body.default_preset, mode=body.default_mode)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from None
        await manage.set_entry_config(profile(), "agent-loop", defaults, merge=True, preflight=False)
        return {**defaults, "presets": loop.presets(), "modes": loop.modes()}

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
