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

| status | condition                                 |
|--------|-------------------------------------------|
| 404    | unknown session                           |
| 409    | running turn, or approvals pending/absent |
| 503    | restart pending (``Retry-After: 2``)      |

``decision``: ``{"type": "approve"}`` or ``{"type": "reject"}``.
"""

from __future__ import annotations

import json
from typing import Any, AsyncIterator

from fastapi import APIRouter, HTTPException, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

name = "pyharness-api"
inject = ["http", "agents"]


class Config(BaseModel):
    prefix: str = "/api"


class NewSession(BaseModel):
    title: str | None = None


class NewMessage(BaseModel):
    content: str = Field(..., min_length=1)


class Approvals(BaseModel):
    decisions: list[dict[str, Any]]


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


def apply(ctx: Any, config: Config) -> None:
    ctx.http.include_router(build_router(ctx), prefix=config.prefix, tags=["pyharness"])
