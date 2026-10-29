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
| GET    | ``/settings/model``          |                               | model settings: default, providers, catalog |
| PUT    | ``/settings/model``          | ``model settings``            | preflight, save, restart when supervised    |
| POST   | ``/settings/model/test``     | ``model settings``            | one short completion: reply, latency        |
| POST   | ``/settings/model/models``   | ``model settings``            | model ids of the endpoint                   |

| status | condition                                 |
|--------|-------------------------------------------|
| 404    | unknown session                           |
| 409    | running turn, or approvals pending/absent |
| 503    | restart pending (``Retry-After: 2``)      |

``decision``: ``{"type": "approve"}`` or ``{"type": "reject"}``.

``model settings``: ``{"provider", "model", "base_url"?, "api_key"?}``. ``api_key`` absent or ``null``
keeps the saved key; ``""`` clears it. Secrets are returned masked.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, AsyncIterator

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


class NewMessage(BaseModel):
    content: str = Field(..., min_length=1)


class Approvals(BaseModel):
    decisions: list[dict[str, Any]]


class ModelSettings(BaseModel):
    provider: str = Field(..., min_length=1)
    model: str = Field("", description="Model name; may contain ':'")
    base_url: str | None = None
    api_key: str | None = Field(None, description="None keeps the saved key; '' clears it.")

    def overrides(self) -> dict[str, Any]:
        """Options that override the saved ones for a probe (an empty key means: use the saved one)."""
        out: dict[str, Any] = {}
        if self.base_url is not None and self.base_url.strip():
            out["base_url"] = self.base_url.strip()
        if self.api_key:
            out["api_key"] = self.api_key
        return out

    def patch(self) -> dict[str, Any]:
        """Config patch for the llm entry (deep-merged)."""
        options: dict[str, Any] = {"base_url": (self.base_url or "").strip() or None}
        if self.api_key is not None:
            options["api_key"] = self.api_key or None
        return {"default": f"{self.provider}:{self.model}", "providers": {self.provider: options}}


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
            "workspace": {"name": workspace.root.name or str(workspace.root), "path": str(workspace.root)} if workspace is not None else None,
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
        return await agents.create_session(title=body.title if body else None)

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
    from pyharness import manage
    from pyharness_llm import LLMConfigError

    router = APIRouter()

    def llm() -> Any:
        service = ctx.get("llm", None)
        if service is None:
            raise HTTPException(503, "model registry (ctx.llm) unavailable")
        return service

    @router.get("/settings/model")
    async def get_model_settings() -> dict[str, Any]:
        lifecycle = ctx.lifecycle
        return {
            **llm().describe(),
            "entry": llm_entry,
            "generation": lifecycle.generation,
            "supervised": lifecycle.supervised,
            "restart_pending": lifecycle.restart_pending is not None,
            "editable": ctx.get("profile", None) is not None,
        }

    @router.put("/settings/model")
    async def put_model_settings(body: ModelSettings) -> dict[str, Any]:
        profile = ctx.get("profile", None)
        if profile is None:
            raise HTTPException(409, "no profile: model settings are read-only in this harness")
        if not body.model.strip() and body.provider != "echo":
            raise HTTPException(422, "model is required")
        body.model = body.model.strip() or "echo"
        result = await manage.set_entry_config(profile, llm_entry, body.patch(), baseline=ctx.loader.snapshot())
        if result.get("application") == "saved":
            lifecycle = ctx.lifecycle
            if lifecycle.supervised:
                # Request after the response is written; the worker exits 75 once holds are released.
                asyncio.get_running_loop().call_later(
                    0.3, lifecycle.request_restart, f"model settings: {body.provider}:{body.model}"
                )
                result["application"] = "restart-scheduled"
            else:
                result["application"] = "saved-restart-required"
        result["default"] = f"{body.provider}:{body.model}"
        result["generation"] = ctx.lifecycle.generation
        return result

    @router.post("/settings/model/test")
    async def test_model_settings(body: ModelSettings) -> dict[str, Any]:
        try:
            return await llm().probe(body.provider, body.model.strip() or "echo", **body.overrides())
        except LLMConfigError as exc:
            return {"ok": False, "error": str(exc)}

    @router.post("/settings/model/models")
    async def list_models(body: ModelSettings) -> dict[str, Any]:
        try:
            return {"ok": True, **await llm().list_models(body.provider, **body.overrides())}
        except LLMConfigError as exc:
            return {"ok": False, "error": str(exc), "models": []}

    return router


def apply(ctx: Any, config: Config) -> None:
    ctx.http.include_router(build_router(ctx), prefix=config.prefix, tags=["pyharness"])
    ctx.http.include_router(build_settings_router(ctx, config.llm_entry), prefix=config.prefix, tags=["pyharness"])
