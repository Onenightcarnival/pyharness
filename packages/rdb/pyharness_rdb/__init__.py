"""``ctx.rdb``: relational database workbench — SQLite / PostgreSQL / GaussDB / MySQL (MariaDB).

| member      | contract                                                                  |
|-------------|---------------------------------------------------------------------------|
| ``store``   | :class:`ProfileStore`: connection profiles (passwords in the credential store) and the agent-access setting |
| ``pool``    | :class:`Pool`: one live connection per profile, idle ones closed          |
| ``sync()``  | register the ``db_*`` tools and prompt section while agent access is on  |

| config         | meaning                                                                 |
|----------------|-------------------------------------------------------------------------|
| ``path``       | profiles file (default ``<profile data>/toolkit/rdb.json``)             |
| ``approval``   | approval gate for ``db_execute`` (default none; the tool needs ``confirm=true`` and a writable connection) |

Tools (shapes as dsh-rdb): ``db_connections``, ``db_schema``, ``db_query`` (one read-only statement), ``db_explain``,
``db_execute`` (writes in one transaction, only on connections marked "allow agent writes"). Routes under ``/api/rdb``
serve the Database page: profiles, settings, test, schemas, tables, columns, ddl, rows (paged, filtered, sorted),
query, execute, changes (grid edits as SQL, previewed then applied) and ``export.csv``.
"""

from __future__ import annotations

import asyncio
import json
import re
import time
import warnings
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response
from langchain_core.tools import tool
from pydantic import BaseModel, Field

from pyharness import Service

from . import engine as eng
from .engine import EngineError, Pool, QueryResult
from .store import ProfileStore, StoreError

PROMPT_ORDER = 153
TOOL_MAX_ROWS = 500
TOOL_DEFAULT_ROWS = 200

GUIDANCE = (
    "The database workbench (SQLite / PostgreSQL / MySQL / GaussDB) is installed and the user allowed its tools. "
    "db_connections lists the connections the user configured on the Database page (refer to them by name); db_schema shows "
    "schemas, tables, or one table's columns / indexes / DDL (look before writing SQL); db_query runs ONE read-only statement "
    "(SELECT / WITH / EXPLAIN / SHOW; rows are capped, so add WHERE / LIMIT on large tables); db_explain shows the plan; "
    "db_execute runs write statements in one transaction, only on connections where the user enabled agent writes, and only "
    "after you showed the user the exact SQL and they agreed (then call with confirm=true; a failure rolls everything back). "
    "Credentials are configured in the UI; tools never return or need passwords. When the user mentions databases, tables, "
    "SQL, PostgreSQL, MySQL, GaussDB or SQLite they mean this workbench."
)


class Config(BaseModel):
    path: str | None = Field(None, description="Profiles file; default <profile data>/toolkit/rdb.json.")
    approval: bool | dict[str, Any] = Field(False, description="Approval gate for db_execute.")
    idle_close_seconds: float = 600.0


def _target_of(p: dict[str, Any]) -> str:
    if p["kind"] == "sqlite":
        return p["file"]
    text = f"{p['user']}@{','.join(eng.host_entries(p['host'], int(p['port'])))}/{p['database']}"
    return text + (f" (target {p['targetSessionAttrs']})" if p.get("targetSessionAttrs", "any") != "any" else "")


class RdbService(Service):
    """Database workbench: profiles, connections, tools, routes and the Database page module."""

    key = "rdb"
    name = "pyharness-rdb"
    inject = ["tools", "prompt", "http"]
    Config = Config

    def __init__(self, ctx: Any, config: Config) -> None:
        super().__init__(ctx, config)
        self.store: ProfileStore | None = None
        self.pool = Pool(idle_close_s=config.idle_close_seconds)
        self._tool_disposers: list[Any] = []
        self._prompt_disposer: Any = None
        self._sweeper: asyncio.Task[Any] | None = None

    # ------------------------------------------------------------------ lifecycle
    def _path(self) -> Path:
        if self.config.path:
            return Path(self.config.path).expanduser()
        profile = self.ctx.get("profile", None)
        base = Path(profile.data) if profile is not None and hasattr(profile, "data") else Path.home() / ".pyharness" / "data"
        return base / "toolkit" / "rdb.json"

    async def start(self) -> None:
        profile = self.ctx.get("profile", None)
        credentials = profile.credentials if profile is not None and hasattr(profile, "credentials") else _MemoryCredentials()
        self.store = ProfileStore(self._path(), credentials)
        self.store.subscribe(self.sync)
        self.ctx.http.include_router(self._router(), prefix="/api", tags=["pyharness-rdb"])
        self.sync()
        self._sweeper = asyncio.create_task(self._sweep())
        webui = self.ctx.get("webui", None)
        if webui is not None and hasattr(webui, "register_client"):
            webui.register_client(Path(__file__).with_name("client.js"))

    async def stop(self) -> None:
        if self._sweeper:
            self._sweeper.cancel()
        self._unregister()
        await asyncio.to_thread(self.pool.close_all)

    async def _sweep(self) -> None:
        while True:
            await asyncio.sleep(60)
            await asyncio.to_thread(self.pool.sweep)

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
            self._tool_disposers = [
                self.ctx.tools.register(self._connections_tool(), tags=("db",)),
                self.ctx.tools.register(self._schema_tool(), tags=("db",)),
                self.ctx.tools.register(self._query_tool(), tags=("db",)),
                self.ctx.tools.register(self._explain_tool(), tags=("db",)),
                self.ctx.tools.register(self._execute_tool(), approval=self.config.approval, tags=("db", "db-write")),
            ]
            self._prompt_disposer = self.ctx.prompt.add("plugin:rdb", GUIDANCE, order=PROMPT_ORDER)
        elif not on and self._tool_disposers:
            self._unregister()
        return bool(self._tool_disposers)

    # ------------------------------------------------------------------ connections
    def profile(self, id_or_name: str) -> dict[str, Any]:
        assert self.store is not None
        p = self.store.find(id_or_name)
        if p is None:
            raise EngineError(f"unknown connection '{id_or_name}' (configure it in the database panel first)")
        return p

    def driver(self, profile: dict[str, Any]) -> eng.Driver:
        assert self.store is not None
        return self.pool.get(profile, self.store.password(profile["id"]))

    async def run(self, id_or_name: str, fn: Any) -> Any:
        """``fn(driver)`` in a worker thread for the connection of a profile."""
        profile = self.profile(id_or_name)
        return await asyncio.to_thread(lambda: fn(self.driver(profile)))

    async def test(self, pid: str) -> dict[str, Any]:
        started = time.perf_counter()
        try:
            profile = self.profile(pid)
            driver = await asyncio.to_thread(lambda: self.driver(profile))
            version = await asyncio.to_thread(driver.server_version)
            out: dict[str, Any] = {"ok": True, "latencyMs": int((time.perf_counter() - started) * 1000), "serverVersion": version}
            if driver.node:
                out["node"] = driver.node
            return out
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "latencyMs": int((time.perf_counter() - started) * 1000), "error": str(exc).strip()}

    # ------------------------------------------------------------------ tools
    def _connections_tool(self):
        service = self

        @tool(
            "db_connections",
            description="List the database connections configured in the Database page (name, kind, host, database, whether writes are allowed). "
            "Every other db_* tool takes one of these names. Triggers: database, SQL, table, query, PostgreSQL, MySQL, MariaDB, GaussDB, SQLite, 数据库, 查表.",
        )
        def db_connections() -> str:
            assert service.store is not None
            profiles = [service.store.summary(p) for p in service.store.profiles()]
            if not profiles:
                return "no database connections configured (the user adds them in the database panel)"
            lines = ["name | kind | target | writes", "--- | --- | --- | ---"]
            lines += [f"{p['name']} | {p['kind']} | {_target_of(p)} | {'allowed' if p['allowWrite'] else 'read-only'}" for p in profiles]
            return "\n".join(lines)

        return db_connections

    def _schema_tool(self):
        service = self
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")  # the `schema` parameter (dsh's name) shadows a BaseModel attribute
            return self._make_schema_tool(service)

    @staticmethod
    def _make_schema_tool(service: RdbService):
        @tool(
            "db_schema",
            description="Inspect structure: without `table`, list schemas and the tables/views of one schema (default schema when omitted); "
            "with `table`, return its columns (type, nullable, default, primary key), indexes and DDL. Call this before writing SQL against a table you have not seen.",
        )
        async def db_schema(
            connection: str = Field(description="Connection name (or id) from db_connections."),
            schema: str | None = Field(
                None,
                description='Schema name (PostgreSQL/GaussDB: default "public"; MySQL: the database, default the connection\'s database; SQLite: "main").',
            ),
            table: str | None = Field(None, description="Table or view name to describe."),
        ) -> str:
            try:
                if table:

                    def describe(d: eng.Driver) -> str:
                        s = schema or d.default_schema
                        info = eng.table_info(d, s, table)
                        try:
                            ddl = d.ddl(s, table, info.table["kind"])
                        except Exception:  # noqa: BLE001
                            ddl = ""
                        head = f"{s}.{table} (table" + (f", ~{info.estimated_rows} rows" if info.estimated_rows is not None else "") + ")"
                        lines = [head, "column | type | nullable | default | pk", "--- | --- | --- | --- | ---"]
                        lines += [
                            f"{c['name']} | {c['type']} | {'yes' if c['nullable'] else 'no'} | {c['defaultValue'] if c['defaultValue'] is not None else ''} | {'PK' if c['primaryKey'] else ''}"
                            for c in info.columns
                        ]
                        if info.indexes:
                            lines += [
                                "",
                                "indexes: "
                                + "; ".join(
                                    f"{i['name']}({', '.join(i['columns'])}){' UNIQUE' if i['unique'] else ''}" for i in info.indexes
                                ),
                            ]
                        if ddl:
                            lines += ["", ddl]
                        return "\n".join(lines)

                    return await service.run(connection, describe)

                def listing(d: eng.Driver) -> str:
                    schemas = d.list_schemas()
                    s = schema or d.default_schema
                    tables = d.list_tables(s)
                    return "\n".join(
                        [f"schemas: {', '.join(schemas)}", ""]
                        + [f"{'[view] ' if t['kind'] == 'view' else ''}{t['schema']}.{t['name']}" for t in tables]
                    )

                return await service.run(connection, listing)
            except Exception as exc:  # noqa: BLE001
                return f"schema lookup failed: {str(exc).strip() or 'unknown error'}"

        return db_schema

    def _query_tool(self):
        service = self

        @tool(
            "db_query",
            description="Run ONE read-only SQL statement (SELECT / WITH / EXPLAIN / SHOW) and return the rows. Anything that writes is refused — use db_execute. "
            "Results are capped (default 200 rows, max 500); add WHERE/LIMIT for large tables.",
        )
        async def db_query(
            connection: str = Field(description="Connection name (or id) from db_connections."),
            sql: str = Field(description="A single read-only statement."),
            maxRows: int | None = Field(None, description="Row cap (default 200, max 500)."),
        ) -> str:
            try:
                res = await service.run(
                    connection,
                    lambda d: eng.run_query(d, sql, allow_write=False, max_rows=min(TOOL_MAX_ROWS, maxRows or TOOL_DEFAULT_ROWS)),
                )
                return eng.human_table(res)
            except Exception as exc:  # noqa: BLE001
                return f"query failed: {str(exc).strip() or 'unknown error'}"

        return db_query

    def _explain_tool(self):
        service = self

        @tool(
            "db_explain",
            description="Show the execution plan of one SELECT (EXPLAIN; PostgreSQL/GaussDB and MySQL use EXPLAIN, SQLite uses EXPLAIN QUERY PLAN). Read-only.",
        )
        async def db_explain(
            connection: str = Field(description="Connection name (or id) from db_connections."),
            sql: str = Field(description="The statement to explain."),
        ) -> str:
            try:

                def go(d: eng.Driver) -> str:
                    body = re.sub(r"^\s*explain(\s+query\s+plan)?\s+", "", sql, flags=re.I)
                    prefix = "EXPLAIN QUERY PLAN " if d.kind == "sqlite" else "EXPLAIN "
                    res = eng.run_query(d, prefix + body, allow_write=False, max_rows=TOOL_MAX_ROWS)
                    return "\n".join(" | ".join("" if v is None else str(v) for v in row) for row in res.rows)

                return await service.run(connection, go)
            except Exception as exc:  # noqa: BLE001
                return f"explain failed: {str(exc).strip() or 'unknown error'}"

        return db_explain

    def _execute_tool(self):
        service = self

        @tool(
            "db_execute",
            description="Run write statements (INSERT / UPDATE / DELETE / DDL) inside ONE transaction; all succeed or none apply. Only works on connections where the "
            "user enabled writes, and only with confirm=true — show the user the exact SQL and get agreement first. Prefer WHERE clauses on primary keys; "
            "check with db_query before and after.",
        )
        async def db_execute(
            connection: str = Field(description="Connection name (or id) from db_connections."),
            statements: list[str] = Field(description="Statements to run in order, one per entry."),
            confirm: bool = Field(description="Must be true; set only after the user explicitly confirmed these statements."),
        ) -> str:
            if confirm is not True:
                return "execute failed (rolled back): refused: confirm must be true (ask the user first)"
            try:
                profile = service.profile(connection)
                if not profile.get("allowWrite"):
                    return f"execute failed (rolled back): refused: connection '{profile['name']}' is read-only for the agent (the user can enable writes in the database panel)"
                affected = await service.run(connection, lambda d: d.transaction([{"sql": s} for s in statements], eng.DEFAULT_TIMEOUT_MS))
                return f"executed {len(statements)} statement(s) in one transaction, {affected or 0} row(s) affected"
            except Exception as exc:  # noqa: BLE001
                return f"execute failed (rolled back): {str(exc).strip() or 'unknown error'}"

        return db_execute

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
                store().set_settings(agentTools=data.get("agentTools")) if isinstance(data.get("agentTools"), bool) else store().settings()
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
                lambda d: {"info": eng.table_info(d, schema or d.default_schema, table, "view" if kind == "view" else "table").describe()},
            )

        @router.get("/rdb/ddl")
        async def ddl(
            id: str | None = None, schema: str | None = None, table: str | None = None, kind: str | None = None
        ) -> dict[str, Any]:
            if not id or not table:
                raise HTTPException(400, "id and table query parameters are required")
            return await guarded(id, lambda d: {"ddl": d.ddl(schema or d.default_schema, table, "view" if kind == "view" else "table")})

        @router.post("/rdb/rows")
        async def rows(request: Request) -> dict[str, Any]:
            data = await body(request, 256 * 1024)
            if not data.get("id") or not data.get("table"):
                raise HTTPException(400, "id and table are required")
            return await guarded(
                str(data["id"]),
                lambda d: {
                    "page": eng.page_rows(
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
                    "result": eng.run_query(
                        d, str(data["sql"]), allow_write=True, max_rows=data.get("maxRows"), timeout_ms=data.get("timeoutMs")
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
                str(data["id"]), lambda d: {"affected": d.transaction([{"sql": s} for s in statements], eng.DEFAULT_TIMEOUT_MS)}
            )

        @router.post("/rdb/changes")
        async def changes(request: Request) -> dict[str, Any]:
            data = await body(request, 4 * 1024 * 1024)
            if not data.get("id") or not data.get("table") or not isinstance(data.get("changes"), list):
                raise HTTPException(400, "id, table and changes are required")
            return await guarded(
                str(data["id"]),
                lambda d: {
                    "result": eng.grid_changes(
                        d, data.get("schema") or d.default_schema, str(data["table"]), data["changes"], bool(data.get("apply"))
                    )
                },
            )

        @router.get("/rdb/export.csv")
        async def export_csv(id: str | None = None, sql: str | None = None, name: str | None = None) -> Response:
            if not id or not sql:
                raise HTTPException(400, "id and sql query parameters are required")
            res: QueryResult = await guarded(id, lambda d: eng.run_query(d, sql, allow_write=False, max_rows=100000, timeout_ms=120000))
            safe = re.sub(r"[^\w.-]+", "_", name or "export")
            return Response(
                content="﻿" + eng.to_csv(res),
                media_type="text/csv; charset=utf-8",
                headers={
                    "content-disposition": f'attachment; filename="{safe}.csv"',
                    "cache-control": "no-store",
                    "x-content-type-options": "nosniff",
                },
            )

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


__all__ = ["GUIDANCE", "RdbService"]
