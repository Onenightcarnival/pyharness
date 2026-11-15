"""
FastAPI routes under ``/api/rdb`` for the Database page: profiles, settings, test, schemas, tables, columns, ddl,
rows, query, execute, changes and ``export.csv``.
"""

from __future__ import annotations

import asyncio
import json
import re
from typing import Any, Protocol

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response

from .driver import DEFAULT_TIMEOUT_MS, EngineError, QueryResult
from .pool import Pool
from .query import grid_changes, page_rows, run_query, table_info, to_csv
from .store import ProfileStore, StoreError


class Host(Protocol):
    """The service, as the routes use it."""

    store: ProfileStore | None
    pool: Pool

    async def run(self, id_or_name: str, fn: Any) -> Any: ...
    async def test(self, pid: str) -> dict[str, Any]: ...
    def sync(self) -> bool: ...


def build_router(service: Host) -> APIRouter:
    """The Database page routes bound to a service."""
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

    async def guarded(id_or_name: str, fn: Any) -> Any:
        try:
            return await service.run(id_or_name, fn)
        except (EngineError, StoreError) as exc:
            raise HTTPException(400, str(exc)) from exc
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(400, str(exc).strip() or type(exc).__name__) from exc

    @router.get("/rdb/profiles")
    async def list_profiles() -> dict[str, Any]:
        return {"profiles": [store().summary(p) for p in store().profiles()]}

    @router.post("/rdb/profiles", status_code=201)
    async def create_profile(request: Request) -> dict[str, Any]:
        try:
            return {"profile": store().create(await body(request))}
        except StoreError as exc:
            raise HTTPException(400, str(exc)) from exc

    @router.patch("/rdb/profiles")
    async def update_profile(request: Request, id: str | None = None) -> dict[str, Any]:
        if not id:
            raise HTTPException(400, "id query parameter is required")
        try:
            out = {"profile": store().update(id, await body(request))}
        except StoreError as exc:
            raise HTTPException(400, str(exc)) from exc
        await asyncio.to_thread(service.pool.drop, id)
        return out

    @router.delete("/rdb/profiles")
    async def delete_profile(id: str | None = None) -> dict[str, Any]:
        if not id:
            raise HTTPException(400, "id query parameter is required")
        try:
            store().delete(id)
        except StoreError as exc:
            raise HTTPException(400, str(exc)) from exc
        await asyncio.to_thread(service.pool.drop, id)
        return {"ok": True}

    @router.get("/rdb/settings")
    async def get_settings() -> dict[str, Any]:
        return {"settings": store().settings()}

    @router.post("/rdb/settings")
    async def post_settings(request: Request) -> dict[str, Any]:
        data = await body(request)
        settings = (
            store().set_settings(agentTools=data.get("agentTools"))
            if isinstance(data.get("agentTools"), bool)
            else store().settings()
        )
        service.sync()
        return {"settings": settings}

    @router.post("/rdb/test")
    async def test_connection(request: Request) -> dict[str, Any]:
        data = await body(request)
        if not data.get("id"):
            raise HTTPException(400, "id is required")
        return {"result": await service.test(str(data["id"]))}

    @router.get("/rdb/schemas")
    async def schemas(id: str | None = None) -> dict[str, Any]:
        if not id:
            raise HTTPException(400, "id query parameter is required")
        return await guarded(id, lambda d: {"schemas": d.list_schemas(), "defaultSchema": d.default_schema})

    @router.get("/rdb/tables")
    async def tables(id: str | None = None, schema: str | None = None) -> dict[str, Any]:
        if not id:
            raise HTTPException(400, "id query parameter is required")
        return await guarded(id, lambda d: {"tables": d.list_tables(schema or d.default_schema)})

    @router.get("/rdb/columns")
    async def columns(
        id: str | None = None, schema: str | None = None, table: str | None = None, kind: str | None = None
    ) -> dict[str, Any]:
        if not id or not table:
            raise HTTPException(400, "id and table query parameters are required")
        return await guarded(
            id,
            lambda d: {
                "info": table_info(
                    d, schema or d.default_schema, table, "view" if kind == "view" else "table"
                ).describe()
            },
        )

    @router.get("/rdb/ddl")
    async def ddl(
        id: str | None = None, schema: str | None = None, table: str | None = None, kind: str | None = None
    ) -> dict[str, Any]:
        if not id or not table:
            raise HTTPException(400, "id and table query parameters are required")
        return await guarded(
            id, lambda d: {"ddl": d.ddl(schema or d.default_schema, table, "view" if kind == "view" else "table")}
        )

    @router.post("/rdb/rows")
    async def rows(request: Request) -> dict[str, Any]:
        data = await body(request, 256 * 1024)
        if not data.get("id") or not data.get("table"):
            raise HTTPException(400, "id and table are required")
        return await guarded(
            str(data["id"]),
            lambda d: {
                "page": page_rows(
                    d,
                    data.get("schema") or d.default_schema,
                    str(data["table"]),
                    offset=int(data.get("offset") or 0),
                    limit=int(data.get("limit") or 100),
                    sort=data.get("sort") if isinstance(data.get("sort"), dict) else None,
                    filters=data.get("filters") if isinstance(data.get("filters"), list) else None,
                )  # fmt: skip
            },
        )

    @router.post("/rdb/query")
    async def query(request: Request) -> dict[str, Any]:
        data = await body(request, 1024 * 1024)
        if not data.get("id") or not data.get("sql"):
            raise HTTPException(400, "id and sql are required")
        return await guarded(
            str(data["id"]),
            lambda d: {
                "result": run_query(
                    d,
                    str(data["sql"]),
                    allow_write=True,
                    max_rows=data.get("maxRows"),
                    timeout_ms=data.get("timeoutMs"),
                ).describe()
            },
        )

    @router.post("/rdb/execute")
    async def execute(request: Request) -> dict[str, Any]:
        data = await body(request, 1024 * 1024)
        statements = [s for s in (data.get("statements") or []) if isinstance(s, str)]
        if not data.get("id") or not statements:
            raise HTTPException(400, "id and statements are required")
        return await guarded(
            str(data["id"]),
            lambda d: {"affected": d.transaction([{"sql": s} for s in statements], DEFAULT_TIMEOUT_MS)},
        )

    @router.post("/rdb/changes")
    async def changes(request: Request) -> dict[str, Any]:
        data = await body(request, 4 * 1024 * 1024)
        if not data.get("id") or not data.get("table") or not isinstance(data.get("changes"), list):
            raise HTTPException(400, "id, table and changes are required")
        return await guarded(
            str(data["id"]),
            lambda d: {
                "result": grid_changes(
                    d,
                    data.get("schema") or d.default_schema,
                    str(data["table"]),
                    data["changes"],
                    bool(data.get("apply")),
                )
            },
        )

    @router.get("/rdb/export.csv")
    async def export_csv(id: str | None = None, sql: str | None = None, name: str | None = None) -> Response:
        if not id or not sql:
            raise HTTPException(400, "id and sql query parameters are required")
        res: QueryResult = await guarded(
            id, lambda d: run_query(d, sql, allow_write=False, max_rows=100000, timeout_ms=120000)
        )
        safe = re.sub(r"[^\w.-]+", "_", name or "export")
        return Response(
            content="﻿" + to_csv(res),
            media_type="text/csv; charset=utf-8",
            headers={
                "content-disposition": f'attachment; filename="{safe}.csv"',
                "cache-control": "no-store",
                "x-content-type-options": "nosniff",
            },
        )

    return router
