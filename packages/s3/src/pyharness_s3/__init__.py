"""``ctx.s3``: S3-compatible object storage browser (MinIO / OSS / COS / R2 / AWS).

| member        | contract                                                                       |
|---------------|--------------------------------------------------------------------------------|
| ``store``     | :class:`ProfileStore`: bucket profiles (secret keys in the credential store), the agent-access setting |
| ``bucket(p)`` | :class:`Bucket` for a profile (boto3 client cached per profile)                |
| ``sync()``    | register the ``s3_*`` tools and prompt section while agent access is on       |

| config         | meaning                                                                  |
|----------------|--------------------------------------------------------------------------|
| ``path``       | profiles file (default ``<profile data>/toolkit/s3.json``)               |
| ``approval``   | approval gate for ``s3_delete`` (default none; the tool needs ``confirm=true``) |

A profile is one bucket (endpoint, region, keys, path-style flag, optional scope prefix); every key the tools and
routes see is relative to that prefix. Tools (shapes as dsh-s3): ``s3_buckets``, ``s3_list``, ``s3_stat``, ``s3_get``,
``s3_put``, ``s3_upload``, ``s3_download``, ``s3_copy``, ``s3_presign``, ``s3_mkdir``, ``s3_delete``. Routes under
``/api/s3`` serve the S3 page: profiles, settings, test, list, stat, object (download / inline preview), text, upload
(raw body), delete, folder, presign, copy.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import tempfile
import warnings
from pathlib import Path
from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from langchain_core.tools import tool
from pydantic import BaseModel, ConfigDict, Field

from pyharness import Service

from . import engine as eng
from .engine import PREVIEWABLE, Bucket, S3Error, clean_key, error_text, guess_mime, human
from .store import ProfileStore, StoreError

PROMPT_ORDER = 152
TOOL_LIST_MAX = 500
TOOL_LIST_DEFAULT = 200
PREVIEW_TEXT_BYTES = 512 * 1024
MAX_UPLOAD_BYTES = 50 * 1024 * 1024 * 1024

GUIDANCE = (
    "The S3 object storage browser is installed and the user allowed its tools. s3_buckets lists the bucket profiles the user "
    "configured on the S3 page (refer to them by profile name); s3_list lists objects one level at a time or recursively "
    "(paginated; narrow large buckets with prefix); s3_stat reads metadata; s3_get reads a text object; s3_put writes a text "
    "object; s3_upload / s3_download move files between this machine and the bucket; s3_copy copies or moves server-side; "
    "s3_presign makes a time-limited share link; s3_mkdir creates a folder marker; s3_delete deletes (irreversible: list first, "
    "confirm each item with the user, then call with confirm=true). All keys are relative to the profile's prefix; credentials "
    "are configured in the UI and tools never return or need them. Local files use the local read / write / edit / bash tools; "
    "s3_* only touch objects in the bucket. When the user mentions S3, buckets, object storage, MinIO, OSS, COS, R2 or cloud "
    "storage files they mean this browser."
)
PROFILE_DOC = "Bucket profile name (or id) from s3_buckets."


class CopyArgs(BaseModel):
    """``s3_copy`` arguments; ``from`` (dsh's name) is a Python keyword, so the field is ``from_`` with that alias."""

    model_config = ConfigDict(populate_by_name=True)
    profile: str = Field(description=PROFILE_DOC)
    from_: str = Field(alias="from", description="Source key.")
    to: str = Field(description="Destination key.")
    move: bool | None = Field(None, description="Delete the source after copying (rename).")


class Config(BaseModel):
    path: str | None = Field(None, description="Profiles file; default <profile data>/toolkit/s3.json.")
    approval: bool | dict[str, Any] = Field(False, description="Approval gate for s3_delete.")


def _ok(**fields: Any) -> dict[str, Any]:
    return {"ok": True, **fields}


def _fail(exc: BaseException) -> dict[str, Any]:
    return {"ok": False, "error": error_text(exc)}


class S3Service(Service):
    """S3 browser: profiles, clients, tools, routes and the S3 page module."""

    key = "s3"
    name = "pyharness-s3"
    inject = ["tools", "prompt", "http"]
    Config = Config

    def __init__(self, ctx: Any, config: Config) -> None:
        super().__init__(ctx, config)
        self.store: ProfileStore | None = None
        self.make_client = eng.make_client
        self._clients: dict[str, tuple[Any, int]] = {}
        self._tool_disposers: list[Any] = []
        self._prompt_disposer: Any = None

    # ------------------------------------------------------------------ lifecycle
    def _path(self) -> Path:
        if self.config.path:
            return Path(self.config.path).expanduser()
        profile = self.ctx.get("profile", None)
        base = Path(profile.data) if profile is not None and hasattr(profile, "data") else Path.home() / ".pyharness" / "data"
        return base / "toolkit" / "s3.json"

    async def start(self) -> None:
        profile = self.ctx.get("profile", None)
        credentials = profile.credentials if profile is not None and hasattr(profile, "credentials") else _MemoryCredentials()
        self.store = ProfileStore(self._path(), credentials)
        self.store.subscribe(self._on_store_change)
        self.ctx.http.include_router(self._router(), prefix="/api", tags=["pyharness-s3"])
        self.sync()
        webui = self.ctx.get("webui", None)
        if webui is not None and hasattr(webui, "register_client"):
            webui.register_client(Path(__file__).with_name("client.js"))

    async def stop(self) -> None:
        self._unregister()
        self._clients.clear()

    def _on_store_change(self) -> None:
        self._clients.clear()
        self.sync()

    def _unregister(self) -> None:
        for d in self._tool_disposers:
            d()
        self._tool_disposers = []
        if self._prompt_disposer is not None:
            self._prompt_disposer()
            self._prompt_disposer = None

    def sync(self) -> bool:
        assert self.store is not None
        on = bool(self.store.settings().get("agentTools"))
        if on and not self._tool_disposers:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                tools = self._tools()
            self._tool_disposers = [
                self.ctx.tools.register(t, approval=self.config.approval if t.name == "s3_delete" else False, tags=("s3",)) for t in tools
            ]
            self._prompt_disposer = self.ctx.prompt.add("plugin:s3", GUIDANCE, order=PROMPT_ORDER)
        elif not on and self._tool_disposers:
            self._unregister()
        return bool(self._tool_disposers)

    # ------------------------------------------------------------------ buckets
    def profile(self, id_or_name: str) -> dict[str, Any]:
        assert self.store is not None
        p = self.store.find(id_or_name)
        if p is None:
            raise S3Error(f"unknown bucket profile '{id_or_name}' (configure it in the S3 panel first)")
        return p

    def bucket(self, profile: dict[str, Any]) -> Bucket:
        assert self.store is not None
        entry = self._clients.get(profile["id"])
        if entry is None or entry[1] != profile.get("updatedAt"):
            client = self.make_client(profile, self.store.secret(profile["id"]))
            self._clients[profile["id"]] = (client, int(profile.get("updatedAt") or 0))
            entry = self._clients[profile["id"]]
        return Bucket(entry[0], profile)

    async def run(self, id_or_name: str, fn: Any) -> Any:
        profile = self.profile(id_or_name)
        return await asyncio.to_thread(lambda: fn(self.bucket(profile)))

    # ------------------------------------------------------------------ tools
    def _tools(self) -> list[Any]:
        service = self

        @tool(
            "s3_buckets",
            description="List the S3-compatible bucket profiles configured in the S3 panel (name, bucket, endpoint, region, key prefix). Every other s3_* tool takes one "
            "of these profile names. Triggers: S3, bucket, object storage, MinIO, OSS, COS, R2, cloud storage files.",
        )
        def s3_buckets() -> str:
            assert service.store is not None
            profiles = [service.store.summary(p) for p in service.store.profiles()]
            if not profiles:
                return "no bucket profiles configured (the user adds them in the S3 panel)"
            lines = ["name | bucket | endpoint | region | prefix", "--- | --- | --- | --- | ---"]
            lines += [f"{p['name']} | {p['bucket']} | {p['endpoint'] or '(aws)'} | {p['region']} | {p['prefix'] or '/'}" for p in profiles]
            return "\n".join(lines)

        @tool(
            "s3_list",
            description='List one "directory" level of a bucket profile: sub-prefixes (folders) and objects directly under `prefix` (delimiter "/"). Paginated — pass `token` '
            "from the previous result to continue. Set `recursive` to walk every object under the prefix instead (capped by `max`). Keys are relative to the profile prefix.",
        )
        async def s3_list(
            profile: str = Field(description=PROFILE_DOC),
            prefix: str | None = Field(None, description='Key prefix to list under, e.g. "logs/2026/" (empty = root of the profile).'),
            token: str | None = Field(None, description="Continuation token from a previous truncated page."),
            max: int | None = Field(None, description="Max entries to return (default 200, cap 500)."),
            recursive: bool | None = Field(None, description="Walk all objects under the prefix (no folder grouping)."),
        ) -> str:
            cap = min(TOOL_LIST_MAX, max or TOOL_LIST_DEFAULT) if max is None or max > 0 else 1
            try:

                def go(b: Bucket) -> dict[str, Any]:
                    if recursive:
                        objects: list[dict[str, Any]] = []
                        truncated = False
                        for o in b.walk(prefix or ""):
                            if len(objects) >= cap:
                                truncated = True
                                break
                            objects.append(o)
                        return {"prefix": prefix or "", "folders": [], "objects": objects, "truncated": truncated}
                    return b.list(prefix or "", token, cap)

                page = await service.run(profile, go)
            except Exception as exc:  # noqa: BLE001
                return f"list failed: {error_text(exc) or 'unknown error'}"
            lines = [f"prefix: {page['prefix'] or '/'}"]
            lines += [f"[dir]  {f}" for f in page["folders"]]
            lines += [f"{human(o['size']).rjust(10)}  {o['lastModified'][:19].replace('T', ' ')}  {o['key']}" for o in page["objects"]]
            if not page["folders"] and not page["objects"]:
                lines.append("(empty)")
            if page["truncated"]:
                lines.append(
                    f"… truncated; continue with token={page['nextToken']}"
                    if page.get("nextToken")
                    else "… truncated at max; raise max or narrow the prefix"
                )
            return "\n".join(lines)

        @tool("s3_stat", description="HEAD one object: size, content type, last modified, ETag, storage class, user metadata.")
        async def s3_stat(
            profile: str = Field(description=PROFILE_DOC), key: str = Field(description="Object key (relative to the profile prefix).")
        ) -> str:
            try:
                s = await service.run(profile, lambda b: b.stat(key))
            except Exception as exc:  # noqa: BLE001
                return f"stat failed: {error_text(exc) or 'unknown error'}"
            lines = [
                f"key: {s['key']}",
                f"size: {human(s['size'])} ({s['size']} bytes)",
                f"content-type: {s.get('contentType') or '-'}",
                f"last-modified: {s.get('lastModified') or '-'}",
                f"etag: {s.get('etag') or '-'}",
                f"storage-class: {s.get('storageClass') or 'STANDARD'}",
            ]
            lines.append(
                "metadata:\n" + "\n".join(f"  {k}: {v}" for k, v in s["metadata"].items()) if s["metadata"] else "metadata: (none)"
            )
            return "\n".join(lines)

        @tool(
            "s3_get",
            description="Read a TEXT object (config, log, CSV, JSON, HTML…) from a bucket and return its content. Bounded by maxBytes (default 200 KiB, cap 2097152); binary "
            "objects are rejected — use s3_download for those.",
        )
        async def s3_get(
            profile: str = Field(description=PROFILE_DOC),
            key: str = Field(description="Object key (relative to the profile prefix)."),
            maxBytes: int | None = Field(None, description="Read at most this many bytes."),
        ) -> str:
            try:
                r = await service.run(profile, lambda b: b.get_text(key, maxBytes or 200 * 1024))
            except Exception as exc:  # noqa: BLE001
                return f"read failed: {error_text(exc) or 'unknown error'}"
            return r["text"] + (
                f"\n[truncated: showing the first part of {r['size']} bytes; raise maxBytes or s3_download the object]"
                if r["truncated"]
                else ""
            )

        @tool(
            "s3_put",
            description="Write a text object (create or overwrite) with the given content. For files already on this machine use s3_upload instead. Overwrites silently — s3_stat first if the key may exist.",
        )
        async def s3_put(
            profile: str = Field(description=PROFILE_DOC),
            key: str = Field(description="Destination key (relative to the profile prefix)."),
            content: str = Field(description="UTF-8 text content."),
            contentType: str | None = Field(None, description="MIME type (default: guessed from the key extension)."),
        ) -> str:
            try:
                r = await service.run(profile, lambda b: b.put(key, content.encode("utf-8"), contentType))
            except Exception as exc:  # noqa: BLE001
                return f"write failed: {error_text(exc) or 'unknown error'}"
            return f"wrote {key} ({r['size']} bytes)"

        @tool(
            "s3_upload",
            description="Upload a file FROM this machine (the harness host) to a bucket. Large files use multipart upload automatically.",
        )
        async def s3_upload(
            profile: str = Field(description=PROFILE_DOC),
            localPath: str = Field(description="Absolute path of the source file on THIS machine."),
            key: str = Field(description="Destination key (relative to the profile prefix)."),
        ) -> str:
            try:
                r = await service.run(profile, lambda b: b.upload_file(localPath, key))
            except Exception as exc:  # noqa: BLE001
                return f"upload failed: {error_text(exc) or 'unknown error'}"
            return f"uploaded {localPath} → {key} ({human(r['size'])})"

        @tool(
            "s3_download",
            description="Download one object to a path on this machine (the harness host); parent directories are created. Use this for binary objects or anything larger than s3_get allows.",
        )
        async def s3_download(
            profile: str = Field(description=PROFILE_DOC),
            key: str = Field(description="Object key (relative to the profile prefix)."),
            localPath: str = Field(description="Absolute destination path on THIS machine."),
        ) -> str:
            try:
                r = await service.run(profile, lambda b: b.download_file(key, localPath))
            except Exception as exc:  # noqa: BLE001
                return f"download failed: {error_text(exc) or 'unknown error'}"
            return f"downloaded {key} → {localPath} ({human(r['size'])})"

        @tool(
            "s3_copy",
            description="Server-side copy (or move/rename with move=true) of one object inside the same bucket profile. Objects above 5 GiB are not supported.",
            args_schema=CopyArgs,
        )
        async def s3_copy(profile: str, from_: str, to: str, move: bool | None = None) -> str:
            try:
                await service.run(profile, lambda b: b.copy(from_, to, bool(move)))
            except Exception as exc:  # noqa: BLE001
                return f"copy failed: {error_text(exc) or 'unknown error'}"
            return f"{'moved' if move else 'copied'} {from_} → {to}"

        @tool(
            "s3_presign",
            description="Create a time-limited presigned URL for one object: GET to share a download link, PUT to let someone upload to that key. The URL is the only credential-free way to hand an object to a third party.",
        )
        async def s3_presign(
            profile: str = Field(description=PROFILE_DOC),
            key: str = Field(description="Object key."),
            expiresIn: int | None = Field(None, description="Validity in seconds (default 3600, max 604800)."),
            method: str | None = Field(None, description="GET (default) or PUT."),
        ) -> str:
            try:
                r = await service.run(profile, lambda b: b.presign(key, expiresIn or 3600, "PUT" if method == "PUT" else "GET"))
            except Exception as exc:  # noqa: BLE001
                return f"presign failed: {error_text(exc) or 'unknown error'}"
            return f"{r['url']}\n(expires {r['expiresAt']})"

        @tool(
            "s3_mkdir",
            description='Create an empty "folder" marker (zero-byte object with a trailing slash) so the prefix shows up in listings before it has objects.',
        )
        async def s3_mkdir(
            profile: str = Field(description=PROFILE_DOC), key: str = Field(description='Folder key, e.g. "backups/2026/".')
        ) -> str:
            try:
                await service.run(profile, lambda b: b.mkdir(key))
            except Exception as exc:  # noqa: BLE001
                return f"mkdir failed: {error_text(exc) or 'unknown error'}"
            return f"created folder {key}"

        @tool(
            "s3_delete",
            description='PERMANENTLY delete objects. A key ending in "/" deletes everything under that prefix (recursive). Irreversible unless bucket versioning is on — list first, '
            "show the user exactly what will be deleted, and only call with confirm=true after they agree.",
        )
        async def s3_delete(
            profile: str = Field(description=PROFILE_DOC),
            keys: list[str] = Field(description='Object keys (or prefixes ending in "/") to delete, relative to the profile prefix.'),
            confirm: bool = Field(description="Must be true; set it only after the user explicitly confirmed this exact deletion."),
        ) -> str:
            if confirm is not True:
                return "delete failed: refused: confirm must be true (ask the user first)"
            try:
                r = await service.run(profile, lambda b: b.delete(keys))
            except Exception as exc:  # noqa: BLE001
                return f"delete failed: {error_text(exc) or 'unknown error'}"
            return "\n".join([f"deleted {r['deleted']} object(s)"] + [f"  failed: {e['key']} — {e['error']}" for e in r["errors"]])

        return [s3_buckets, s3_list, s3_stat, s3_get, s3_put, s3_upload, s3_download, s3_copy, s3_presign, s3_mkdir, s3_delete]

    # ------------------------------------------------------------------ routes
    def _router(self) -> APIRouter:
        router = APIRouter()
        service = self

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
                store().set_settings(agentTools=data.get("agentTools")) if isinstance(data.get("agentTools"), bool) else store().settings()
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
        async def list_objects(id: str | None = None, prefix: str = "", token: str | None = None, max: int | None = None) -> dict[str, Any]:
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
            name = os.path.basename(clean_key(key)) or "download"
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
                body_stream.iter_chunks(), media_type=ctype if previewable else "application/octet-stream", headers=headers
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
            spool = tempfile.SpooledTemporaryFile(max_size=PREVIEW_TEXT_BYTES)
            async for chunk in request.stream():
                spool.write(chunk)
            spool.seek(0)
            try:
                await guarded(id, lambda b: b.upload_stream(key, spool, content_type), 500)
            finally:
                spool.close()
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
                str(data["id"]), lambda b: b.presign(str(data["key"]), int(expires), "PUT" if data.get("method") == "PUT" else "GET"), 500
            )

        @router.post("/s3/copy")
        async def copy_object(request: Request) -> dict[str, Any]:
            data = await body(request)
            if not data.get("id") or not data.get("from") or not data.get("to"):
                raise HTTPException(400, "id, from and to are required")
            await guarded(str(data["id"]), lambda b: b.copy(str(data["from"]), str(data["to"]), data.get("move") is True), 500)
            return {"ok": True}

        return router


class _MemoryCredentials:
    def __init__(self) -> None:
        self.data: dict[str, str] = {}

    def get(self, ref: str | None) -> str | None:
        return self.data.get(ref or "")

    def set(self, ref: str, value: str) -> None:
        self.data[ref] = value

    def delete(self, ref: str) -> bool:
        return self.data.pop(ref, None) is not None


__all__ = ["GUIDANCE", "S3Service"]
