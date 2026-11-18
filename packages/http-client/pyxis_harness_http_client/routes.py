from __future__ import annotations

import asyncio
import contextlib
import json
from collections.abc import AsyncIterator
from typing import Any, Protocol

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse

from pyxis_harness import package_toml

from .engine import HttpEngine, PolicyError, SendOptions
from .protocol import DIRECT_TARGET_ID, PANEL_BODY_BYTES
from .store import HistoryStore, RequestStore, StoreError, TargetStore, summarize

_CFG = package_toml(__file__)["routes"]
MAX_SEND_BYTES: int = _CFG["MAX_SEND_BYTES"]
MAX_HISTORY_PAGE: int = _CFG["MAX_HISTORY_PAGE"]
MAX_REQUEST_BYTES: int = _CFG["MAX_REQUEST_BYTES"]
NDJSON_HEADERS = {"cache-control": "no-store", "referrer-policy": "no-referrer", "x-accel-buffering": "no"}


class Host(Protocol):
    """The service, as the routes use it."""

    store: TargetStore
    requests: RequestStore
    history: HistoryStore
    engine: HttpEngine

    def sync(self) -> bool: ...


async def _body(request: Request, limit: int = 64 * 1024) -> dict[str, Any]:
    raw = await request.body()
    try:
        data = json.loads(raw) if raw and len(raw) <= limit else None
    except ValueError:
        data = None
    if not isinstance(data, dict):
        raise HTTPException(400, "invalid JSON body or body too large")
    return data


def _line(value: dict[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False) + "\n"


async def _gone(request: Request) -> None:
    """Return once the client has closed the connection; the request body is already consumed."""
    while (await request.receive())["type"] != "http.disconnect":
        pass


def build_router(service: Host) -> APIRouter:
    router = APIRouter()
    store, requests, history, engine = service.store, service.requests, service.history, service.engine

    def known_scope(target_id: Any) -> bool:
        """A saved request belongs to an existing target or to the direct scope."""
        return target_id == DIRECT_TARGET_ID or any(t["id"] == target_id for t in store.list())

    def checked(action: Any, *args: Any) -> Any:
        try:
            return action(*args)
        except StoreError as exc:
            raise HTTPException(400, str(exc)) from exc

    # ------------------------------------------------------------------ targets
    @router.get("/targets")
    async def list_targets() -> dict[str, Any]:
        return {"targets": [summarize(target) for target in store.list()]}

    @router.post("/targets")
    async def create_target(request: Request) -> dict[str, Any]:
        return {"target": summarize(checked(store.create, await _body(request)))}

    @router.patch("/targets")
    async def update_target(request: Request, id: str) -> dict[str, Any]:
        return {"target": summarize(checked(store.update, id, await _body(request)))}

    @router.delete("/targets")
    async def delete_target(id: str) -> dict[str, Any]:
        checked(store.delete, id)
        requests.delete_by_target(id)
        history.clear(target_id=id)
        return {"ok": True}

    # ------------------------------------------------------------------ saved requests
    @router.get("/requests")
    async def list_requests(target: str | None = None) -> dict[str, Any]:
        return {"requests": requests.list(target or None)}

    @router.post("/requests")
    async def create_request(request: Request) -> dict[str, Any]:
        payload = await _body(request, MAX_REQUEST_BYTES)
        if not known_scope(payload.get("targetId")):
            raise HTTPException(400, f"target '{payload.get('targetId')}' not found")
        return {"request": checked(requests.create, payload)}

    @router.patch("/requests")
    async def update_request(request: Request, id: str) -> dict[str, Any]:
        patch = await _body(request, MAX_REQUEST_BYTES)
        if patch.get("targetId") is not None and not known_scope(patch["targetId"]):
            raise HTTPException(400, f"target '{patch['targetId']}' not found")
        return {"request": checked(requests.update, id, patch)}

    @router.delete("/requests")
    async def delete_request(id: str) -> dict[str, Any]:
        checked(requests.delete, id)
        return {"ok": True}

    # ------------------------------------------------------------------ settings
    @router.get("/settings")
    async def get_settings() -> dict[str, Any]:
        return {"settings": store.settings()}

    @router.post("/settings")
    async def set_settings(request: Request) -> dict[str, Any]:
        settings = checked(store.set_settings, await _body(request))
        service.sync()
        return {"settings": settings}

    # ------------------------------------------------------------------ send
    @router.post("/send")
    async def send(request: Request) -> Response:
        data = await _body(request, MAX_SEND_BYTES)
        target_id = data.get("id") if isinstance(data.get("id"), str) else ""
        if not target_id:
            raise HTTPException(400, "id is required")
        cancel = asyncio.Event()
        options = SendOptions(source="panel", max_body_bytes=PANEL_BODY_BYTES, cancel=cancel, keep_binary=True)
        if "application/x-ndjson" not in request.headers.get("accept", "").lower():
            work = asyncio.ensure_future(engine.send(target_id, data.get("request"), options))
            gone = asyncio.ensure_future(_gone(request))
            await asyncio.wait({work, gone}, return_when=asyncio.FIRST_COMPLETED)
            gone.cancel()
            if not work.done():
                # The client left: the engine records the exchange as cancelled.
                cancel.set()
            try:
                return JSONResponse({"exchange": await work})
            except PolicyError as exc:
                raise HTTPException(400, str(exc)) from exc

        lines: asyncio.Queue[str | None] = asyncio.Queue()
        options.on_stream_start = lambda head: lines.put_nowait(_line({"type": "head", "head": head}))
        options.on_stream_event = lambda event, at: lines.put_nowait(_line({"type": "event", "event": event, "at": at}))

        async def run() -> None:
            try:
                exchange = await engine.send(target_id, data.get("request"), options)
                lines.put_nowait(_line({"type": "done", "exchange": exchange}))
            except PolicyError as exc:
                lines.put_nowait(_line({"type": "error", "error": str(exc)}))
            finally:
                lines.put_nowait(None)

        work = asyncio.ensure_future(run())

        async def stream() -> AsyncIterator[str]:
            try:
                while (line := await lines.get()) is not None:
                    yield line
            finally:
                # A closed connection stops the request; the engine finishes and records it.
                cancel.set()
                with contextlib.suppress(asyncio.CancelledError):
                    await asyncio.shield(work)

        return StreamingResponse(stream(), media_type="application/x-ndjson; charset=utf-8", headers=NDJSON_HEADERS)

    # ------------------------------------------------------------------ history and test
    @router.get("/history")
    async def list_history(target: str | None = None, limit: int = 100) -> dict[str, Any]:
        return {"entries": history.list(target or None, min(MAX_HISTORY_PAGE, max(1, limit)))}

    @router.delete("/history")
    async def clear_history(id: str | None = None, target: str | None = None) -> dict[str, Any]:
        return {"removed": history.clear(id or None, target or None)}

    @router.post("/test")
    async def test_target(request: Request) -> dict[str, Any]:
        data = await _body(request)
        if not isinstance(data.get("id"), str) or not data["id"]:
            raise HTTPException(400, "id is required")
        try:
            return {"result": await engine.test(data["id"])}
        except PolicyError as exc:
            raise HTTPException(400, str(exc)) from exc

    return router
