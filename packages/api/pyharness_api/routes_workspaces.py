"""Workspace routes: the registry (recent, pick, add, rename, forget, browse) and files inside a workspace.

| method | path                     | handler             |
|--------|--------------------------|---------------------|
| GET    | ``/workspaces``          | ``list_workspaces`` |
| POST   | ``/workspaces/pick``     | ``pick_workspace``  |
| POST   | ``/workspaces``          | ``add_workspace``   |
| PUT    | ``/workspaces``          | ``rename_workspace``|
| DELETE | ``/workspaces``          | ``forget_workspace``|
| GET    | ``/workspaces/files``    | ``list_files``      |
| GET    | ``/workspaces/search``   | ``search_files``    |
| GET    | ``/workspaces/file``     | ``read_file``       |
| GET    | ``/workspaces/file/raw`` | ``read_file_raw``   |
| POST   | ``/workspaces/browse``   | ``browse_workspaces``|
"""

from __future__ import annotations

import asyncio
import mimetypes
from typing import Any

from fastapi import APIRouter, HTTPException, Response

from . import references
from .models import WorkspacePath


def build_workspaces_router(ctx: Any) -> APIRouter:
    router = APIRouter()

    @router.get("/workspaces")
    async def list_workspaces() -> dict[str, Any]:
        workspaces = ctx.get("workspace", None)
        if workspaces is None or not hasattr(workspaces, "recent"):
            return {"default": None, "recent": []}
        return {
            "default": workspaces.default.describe(),
            "recent": await workspaces.recent(),
            "picker": workspaces.picker(),
        }

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
        return {
            "root": str(ws.root),
            "path": "/" + real.relative_to(ws.root).as_posix() if real != ws.root else "/",
            "entries": entries,
        }

    @router.get("/workspaces/search")
    async def search_files(q: str = "", root: str | None = None, limit: int = 50) -> dict[str, Any]:
        """Files and directories of a workspace matching ``q`` (for ``@`` references); hidden and dependency
        directories skipped."""
        workspaces = ctx.get("workspace", None)
        if workspaces is None or not hasattr(workspaces, "open"):
            raise HTTPException(503, "workspace registry unavailable")
        try:
            ws = workspaces.open(root)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from None
        return {"entries": await asyncio.to_thread(references.search, ws.root, q, max(1, min(limit, 200)))}

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

    return router
