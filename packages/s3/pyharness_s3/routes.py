from __future__ import annotations

import json
import re
import tempfile
from typing import Any, Protocol
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from . import engine as eng
from .engine import PREVIEWABLE, clean_key, error_text, guess_mime
from .store import ProfileStore, StoreError


class Host(Protocol):
    """The service, as the routes use it."""

    store: ProfileStore | None

    async def run(self, id_or_name: str, fn: Any) -> Any: ...
    def sync(self) -> bool: ...


PREVIEW_TEXT_BYTES = 512 * 1024
MAX_UPLOAD_BYTES = 50 * 1024 * 1024 * 1024


def build_router(service: Host) -> APIRouter:
    """The S3 page routes bound to a service."""
    router = APIRouter()

    def store() -> ProfileStore:
        assert service.store is not None
        return service.store

    async def body(request: Request, limit: int = 64 * 1024) -> dict[str, Any]:
        raw = await request.body()
        if len(raw) > limit:
            raise HTTPException(413, "body too large")
        try:
            data = json.loads(raw) if raw else None
        except ValueError:
            data = None
        if not isinstance(data, dict):
            raise HTTPException(400, "invalid JSON body")
        return data

    async def guarded(pid: str, fn: Any, status: int = 400) -> Any:
        try:
            return await service.run(pid, fn)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status, error_text(exc) or type(exc).__name__) from exc

    @router.get("/s3/profiles")
    async def list_profiles() -> dict[str, Any]:
        return {"profiles": [store().summary(p) for p in store().profiles()]}

    @router.post("/s3/profiles", status_code=201)
    async def create_profile(request: Request) -> dict[str, Any]:
        try:
            return {"profile": store().create(await body(request))}
        except StoreError as exc:
            raise HTTPException(400, str(exc)) from exc

    @router.patch("/s3/profiles")
    async def update_profile(request: Request, id: str | None = None) -> dict[str, Any]:
        if not id:
            raise HTTPException(400, "id query parameter is required")
        try:
            return {"profile": store().update(id, await body(request))}
        except StoreError as exc:
            raise HTTPException(400, str(exc)) from exc

    @router.delete("/s3/profiles")
    async def delete_profile(id: str | None = None) -> dict[str, Any]:
        if not id:
            raise HTTPException(400, "id query parameter is required")
        try:
            store().delete(id)
        except StoreError as exc:
            raise HTTPException(400, str(exc)) from exc
        return {"ok": True}

    @router.get("/s3/settings")
    async def get_settings() -> dict[str, Any]:
        return {"settings": store().settings()}

    @router.post("/s3/settings")
    async def post_settings(request: Request) -> dict[str, Any]:
        data = await body(request)
        settings = (
            store().set_settings(agentTools=data.get("agentTools"))
            if isinstance(data.get("agentTools"), bool)
            else store().settings()
        )
        service.sync()
        return {"settings": settings}

    @router.post("/s3/test")
    async def test_profile(request: Request) -> dict[str, Any]:
        data = await body(request)
        if not data.get("id"):
            raise HTTPException(400, "id is required")
        try:
            return {"result": await service.run(str(data["id"]), lambda b: b.test())}
        except Exception as exc:  # noqa: BLE001
            return {"result": {"ok": False, "latencyMs": 0, "error": error_text(exc)}}

    @router.get("/s3/list")
    async def list_objects(
        id: str | None = None,
        prefix: str = "",
        token: str | None = None,
        max: int | None = None,  # noqa: A002 — query parameter name of the page API
    ) -> dict[str, Any]:
        if not id:
            raise HTTPException(400, "id query parameter is required")
        cap = max if isinstance(max, int) and max > 0 else eng.MAX_PAGE
        return {"page": await guarded(id, lambda b: b.list(prefix, token, cap))}

    @router.get("/s3/stat")
    async def stat_object(id: str | None = None, key: str | None = None) -> dict[str, Any]:
        if not id or key is None:
            raise HTTPException(400, "id and key query parameters are required")
        return {"stat": await guarded(id, lambda b: b.stat(key))}

    @router.get("/s3/text")
    async def text_object(id: str | None = None, key: str | None = None) -> dict[str, Any]:
        if not id or key is None:
            raise HTTPException(400, "id and key query parameters are required")
        out = await guarded(id, lambda b: b.get_text(key, PREVIEW_TEXT_BYTES))
        return {**out, "maxBytes": PREVIEW_TEXT_BYTES}

    @router.get("/s3/object")
    async def get_object(id: str | None = None, key: str | None = None, inline: str | None = None) -> StreamingResponse:
        if not id or key is None:
            raise HTTPException(400, "id and key query parameters are required")
        opened = await guarded(id, lambda b: b.open(key))
        ctype = str(opened["contentType"] or "application/octet-stream")
        previewable = bool(PREVIEWABLE.match(ctype.lower()))
        name = clean_key(key).rsplit("/", 1)[-1] or "download"
        ascii_name = re.sub(r'[^\x20-\x7e]|["\\]', "_", name)
        kind = "inline" if inline == "1" and previewable else "attachment"
        headers = {
            "content-disposition": f"{kind}; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(name)}",
            "x-content-type-options": "nosniff",
            "cache-control": "no-store",
            "referrer-policy": "no-referrer",
        }
        if opened.get("size") is not None:
            headers["content-length"] = str(opened["size"])
        if opened.get("lastModified"):
            headers["last-modified"] = opened["lastModified"].strftime("%a, %d %b %Y %H:%M:%S GMT")
        body_stream = opened["body"]
        return StreamingResponse(
            body_stream.iter_chunks(),
            media_type=ctype if previewable else "application/octet-stream",
            headers=headers,
        )

    @router.api_route("/s3/upload", methods=["PUT", "POST"])
    async def upload(request: Request, id: str | None = None, key: str | None = None) -> dict[str, Any]:
        if not id or not key:
            raise HTTPException(400, "id and key query parameters are required")
        declared = request.headers.get("content-length")
        if declared and int(declared) > MAX_UPLOAD_BYTES:
            raise HTTPException(413, "upload body too large")
        ctype = request.headers.get("content-type") or ""
        content_type = ctype if ctype and ctype != "application/octet-stream" else guess_mime(key)
        with tempfile.SpooledTemporaryFile(max_size=PREVIEW_TEXT_BYTES) as spool:
            async for chunk in request.stream():
                spool.write(chunk)
            spool.seek(0)
            await guarded(id, lambda b: b.upload_stream(key, spool, content_type), 500)
        return {"ok": True, "key": clean_key(key)}

    @router.post("/s3/delete")
    async def delete_objects(request: Request) -> dict[str, Any]:
        data = await body(request, 1024 * 1024)
        keys = [k for k in (data.get("keys") or []) if isinstance(k, str)]
        if not data.get("id") or not keys:
            raise HTTPException(400, "id and a non-empty keys array are required")
        return {"result": await guarded(str(data["id"]), lambda b: b.delete(keys), 500)}

    @router.post("/s3/folder")
    async def make_folder(request: Request) -> dict[str, Any]:
        data = await body(request)
        key = str(data.get("key") or "").strip()
        if not data.get("id") or not key:
            raise HTTPException(400, "id and key are required")
        await guarded(str(data["id"]), lambda b: b.mkdir(key), 500)
        return {"ok": True}

    @router.post("/s3/presign")
    async def presign(request: Request) -> dict[str, Any]:
        data = await body(request)
        if not data.get("id") or not data.get("key"):
            raise HTTPException(400, "id and key are required")
        expires = data.get("expiresIn") if isinstance(data.get("expiresIn"), (int, float)) else 3600
        return await guarded(
            str(data["id"]),
            lambda b: b.presign(str(data["key"]), int(expires), "PUT" if data.get("method") == "PUT" else "GET"),
            500,
        )

    @router.post("/s3/copy")
    async def copy_object(request: Request) -> dict[str, Any]:
        data = await body(request)
        if not data.get("id") or not data.get("from") or not data.get("to"):
            raise HTTPException(400, "id, from and to are required")
        await guarded(
            str(data["id"]), lambda b: b.copy(str(data["from"]), str(data["to"]), data.get("move") is True), 500
        )
        return {"ok": True}

    return router
