"""FastAPI routes under ``/api/memory`` for the Memory page: ``GET`` (state), ``GET ?diff=N``, ``POST`` (commit),
``PATCH`` (agent access), ``DELETE`` (clear)."""

from __future__ import annotations

import json
import re
from typing import Any, Protocol

from fastapi import APIRouter, HTTPException, Request

from .store import MemoryStore, MemoryStoreError


class Host(Protocol):
    """The service, as the routes use it."""

    store: MemoryStore | None

    def sync(self) -> bool: ...


MAX_BODY = 2 * 1024 * 1024


def build_router(service: Host) -> APIRouter:
    """The Memory page routes bound to a service."""
    router = APIRouter()

    def fail(exc: MemoryStoreError) -> HTTPException:
        status = 409 if exc.code in ("conflict", "protected", "busy") else 400
        return HTTPException(status, {"error": exc.code, "detail": exc.detail})

    async def body(request: Request) -> dict[str, Any]:
        raw = await request.body()
        if not raw or len(raw) > MAX_BODY:
            raise HTTPException(400, {"error": "invalid", "detail": "body"})
        try:
            data = json.loads(raw)
        except ValueError:
            data = None
        if not isinstance(data, dict):
            raise HTTPException(400, {"error": "invalid", "detail": "body"})
        return data

    @router.get("/memory")
    async def get_memory(diff: str | None = None) -> dict[str, Any]:
        assert service.store is not None
        if diff is None:
            return service.store.state()
        if not re.match(r"^\d{1,15}$", diff):
            raise HTTPException(404, {"error": "missing", "detail": ""})
        result = service.store.diff(int(diff))
        if result is None:
            raise HTTPException(404, {"error": "missing", "detail": ""})
        return result

    @router.post("/memory")
    async def post_memory(request: Request) -> dict[str, Any]:
        assert service.store is not None
        data = await body(request)
        try:
            return service.store.commit(data, "human", "ui")
        except MemoryStoreError as exc:
            raise fail(exc) from exc

    @router.patch("/memory")
    async def patch_memory(request: Request) -> dict[str, Any]:
        assert service.store is not None
        data = await body(request)
        try:
            state = service.store.set_agent_tools(data.get("agentTools"))
        except MemoryStoreError as exc:
            raise fail(exc) from exc
        service.sync()
        return state

    @router.delete("/memory")
    async def delete_memory(request: Request) -> dict[str, Any]:
        assert service.store is not None
        data = await body(request)
        try:
            return service.store.clear(data.get("baseRevision"))
        except MemoryStoreError as exc:
            raise fail(exc) from exc

    return router
