"""The ``db_*`` LangChain tools (shapes as dsh-rdb); every result is text for the model."""

from __future__ import annotations

import re
import warnings
from string import Template
from textwrap import dedent
from typing import TYPE_CHECKING, Any

from langchain_core.tools import tool
from pydantic import Field

from pyharness import package_prompts

from .driver import DEFAULT_TIMEOUT_MS, Driver, host_entries
from .query import human_table, run_query, table_info

if TYPE_CHECKING:
    from .service import RdbService  # type-only: .service imports this module

PROMPTS = package_prompts(__file__)
TOOL_MAX_ROWS = 500
TOOL_DEFAULT_ROWS = 200


def _target_of(p: dict[str, Any]) -> str:
    if p["kind"] == "sqlite":
        return p["file"]
    text = f"{p['user']}@{','.join(host_entries(p['host'], int(p['port'])))}/{p['database']}"
    return text + (f" (target {p['targetSessionAttrs']})" if p.get("targetSessionAttrs", "any") != "any" else "")


def connections_tool(service: RdbService):
    @tool(
        "db_connections",
        description=PROMPTS["tools"]["db_connections"],
    )
    def db_connections() -> str:
        assert service.store is not None
        profiles = [service.store.summary(p) for p in service.store.profiles()]
        if not profiles:
            return "no database connections configured (the user adds them in the database panel)"
        lines = ["name | kind | target | writes", "--- | --- | --- | ---"]
        lines += [
            f"{p['name']} | {p['kind']} | {_target_of(p)} | {'allowed' if p['allowWrite'] else 'read-only'}"
            for p in profiles
        ]
        return "\n".join(lines)

    return db_connections


def schema_tool(service: RdbService):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")  # the `schema` parameter (dsh's name) shadows a BaseModel attribute
        return _make_schema_tool(service)


def _make_schema_tool(service: RdbService):
    @tool(
        "db_schema",
        description=PROMPTS["tools"]["db_schema"],
    )
    async def db_schema(
        connection: str = Field(description="Connection name (or id) from db_connections."),
        schema: str | None = Field(
            None,
            description=dedent(
                """
                Schema name (PostgreSQL/GaussDB: default "public"; MySQL: the database, default the
                connection's database; SQLite: "main").
                """
            ).strip(),
        ),
        table: str | None = Field(None, description="Table or view name to describe."),
    ) -> str:
        try:
            if table:

                def describe(d: Driver) -> str:
                    s = schema or d.default_schema
                    info = table_info(d, s, table)
                    try:
                        ddl = d.ddl(s, table, info.table["kind"])
                    except Exception:  # noqa: BLE001
                        ddl = ""
                    head = (
                        f"{s}.{table} (table"
                        + (f", ~{info.estimated_rows} rows" if info.estimated_rows is not None else "")
                        + ")"
                    )
                    lines = [head, "column | type | nullable | default | pk", "--- | --- | --- | --- | ---"]
                    lines += [
                        f"{c['name']} | {c['type']} | {'yes' if c['nullable'] else 'no'} | "
                        f"{c['defaultValue'] if c['defaultValue'] is not None else ''} | "
                        f"{'PK' if c['primaryKey'] else ''}"
                        for c in info.columns
                    ]
                    if info.indexes:
                        lines += [
                            "",
                            "indexes: "
                            + "; ".join(
                                f"{i['name']}({', '.join(i['columns'])}){' UNIQUE' if i['unique'] else ''}"
                                for i in info.indexes
                            ),
                        ]
                    if ddl:
                        lines += ["", ddl]
                    return "\n".join(lines)

                return await service.run(connection, describe)

            def listing(d: Driver) -> str:
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


def query_tool(service: RdbService):
    @tool(
        "db_query",
        description=PROMPTS["tools"]["db_query"],
    )
    async def db_query(
        connection: str = Field(description="Connection name (or id) from db_connections."),
        sql: str = Field(description="A single read-only statement."),
        maxRows: int | None = Field(None, description="Row cap (default 200, max 500)."),
    ) -> str:
        try:
            res = await service.run(
                connection,
                lambda d: run_query(
                    d, sql, allow_write=False, max_rows=min(TOOL_MAX_ROWS, maxRows or TOOL_DEFAULT_ROWS)
                ),
            )
            return human_table(res)
        except Exception as exc:  # noqa: BLE001
            return f"query failed: {str(exc).strip() or 'unknown error'}"

    return db_query


def explain_tool(service: RdbService):
    @tool(
        "db_explain",
        description=PROMPTS["tools"]["db_explain"],
    )
    async def db_explain(
        connection: str = Field(description="Connection name (or id) from db_connections."),
        sql: str = Field(description="The statement to explain."),
    ) -> str:
        try:

            def go(d: Driver) -> str:
                body = re.sub(r"^\s*explain(\s+query\s+plan)?\s+", "", sql, flags=re.I)
                prefix = "EXPLAIN QUERY PLAN " if d.kind == "sqlite" else "EXPLAIN "
                res = run_query(d, prefix + body, allow_write=False, max_rows=TOOL_MAX_ROWS)
                return "\n".join(" | ".join("" if v is None else str(v) for v in row) for row in res.rows)

            return await service.run(connection, go)
        except Exception as exc:  # noqa: BLE001
            return f"explain failed: {str(exc).strip() or 'unknown error'}"

    return db_explain


def execute_tool(service: RdbService):
    @tool(
        "db_execute",
        description=PROMPTS["tools"]["db_execute"],
    )
    async def db_execute(
        connection: str = Field(description="Connection name (or id) from db_connections."),
        statements: list[str] = Field(description="Statements to run in order, one per entry."),
        confirm: bool = Field(
            description="Must be true; set only after the user explicitly confirmed these statements."
        ),
    ) -> str:
        if confirm is not True:
            return "execute failed (rolled back): refused: confirm must be true (ask the user first)"
        try:
            profile = service.profile(connection)
            if not profile.get("allowWrite"):
                return Template(PROMPTS["tools"]["read_only"]).substitute(name=profile["name"])
            affected = await service.run(
                connection, lambda d: d.transaction([{"sql": s} for s in statements], DEFAULT_TIMEOUT_MS)
            )
            return f"executed {len(statements)} statement(s) in one transaction, {affected or 0} row(s) affected"
        except Exception as exc:  # noqa: BLE001
            return f"execute failed (rolled back): {str(exc).strip() or 'unknown error'}"

    return db_execute
