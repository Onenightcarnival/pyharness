"""The driver contract: limits, result shapes, host lists, the :class:`Driver` base and the shared cursor runner.
Drivers are synchronous DB-API connections; the service runs them in worker threads, one statement at a time per
connection."""

from __future__ import annotations

import re
import threading
import time
from dataclasses import dataclass
from typing import Any

from pyharness import package_toml

from .sql import command_of, sql_literal, to_js

DEFAULT_MAX_ROWS = 1000
MAX_ROWS_CAP = 100000
DEFAULT_TIMEOUT_MS = 30000
COUNT_TIMEOUT_MS = 10000
CONNECT_TIMEOUT_S = 15
DEFAULT_PORT: dict[str, int] = package_toml(__file__)["driver"]["default_port"]  # kind -> port (0 for sqlite)
KINDS = ("sqlite", "postgres", "gaussdb", "mysql")
TARGETS = ("any", "read-write", "read-only", "primary", "standby", "prefer-standby")


class EngineError(RuntimeError):
    pass


# ---------------------------------------------------------------------- result shapes
@dataclass
class QueryResult:
    columns: list[dict[str, str]]
    rows: list[list[Any]]
    row_count: int
    truncated: bool
    duration_ms: int
    command: str

    def describe(self) -> dict[str, Any]:
        return {
            "columns": self.columns,
            "rows": self.rows,
            "rowCount": self.row_count,
            "truncated": self.truncated,
            "durationMs": self.duration_ms,
            "command": self.command,
        }


@dataclass
class SessionState:
    in_recovery: bool
    read_only: bool


def session_matches(want: str, state: SessionState) -> bool:
    return {
        "any": True,
        "read-write": not state.in_recovery and not state.read_only,
        "read-only": state.in_recovery or state.read_only,
        "primary": not state.in_recovery,
        "standby": state.in_recovery,
    }.get(want, True)


def host_entries(host: str, port: int) -> list[str]:
    out = []
    for h in re.split(r"[\s,]+", host.strip()):
        if not h:
            continue
        if ":" in h and not h.startswith("["):
            h = f"[{h}]"
        out.append(f"{h}:{port}")
    return out


def parse_hosts(host: str) -> list[str]:
    hosts = []
    for h in re.split(r"[\s,]+", host.strip()):
        if h:
            hosts.append(h[1:-1] if h.startswith("[") and h.endswith("]") else h)
    return hosts


# ---------------------------------------------------------------------- drivers
class Driver:
    kind = ""
    mysql = False
    node: str | None = None
    alive = True

    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.last_used = time.monotonic()

    # dialect
    def quote_ident(self, name: str) -> str:
        return '"' + name.replace('"', '""') + '"'

    def placeholder(self, i: int) -> str:
        return "?"

    def cast_to_text(self, expr: str) -> str:
        return f"CAST({expr} AS TEXT)"

    def insert_defaults(self, target: str) -> str:
        return f"INSERT INTO {target} DEFAULT VALUES"

    def literal(self, value: Any) -> str:
        return sql_literal(value, self.mysql)

    @property
    def default_schema(self) -> str:
        return "main"

    # operations (implemented per driver)
    def query(self, sql: str, params: list[Any] | None, max_rows: int, timeout_ms: int) -> QueryResult:
        raise NotImplementedError

    def transaction(self, statements: list[dict[str, Any]], timeout_ms: int) -> int:
        raise NotImplementedError

    def list_schemas(self) -> list[str]:
        raise NotImplementedError

    def list_tables(self, schema: str) -> list[dict[str, str]]:
        raise NotImplementedError

    def columns(self, schema: str, table: str) -> list[dict[str, Any]]:
        raise NotImplementedError

    def indexes(self, schema: str, table: str) -> list[dict[str, Any]]:
        raise NotImplementedError

    def ddl(self, schema: str, table: str, kind: str) -> str:
        raise NotImplementedError

    def estimated_rows(self, schema: str, table: str) -> int | None:
        return None

    def server_version(self) -> str:
        raise NotImplementedError

    def close(self) -> None:
        pass

    # helpers
    def _rows(self, sql: str, params: list[Any] | None = None) -> list[dict[str, Any]]:
        res = self.query(sql, params, MAX_ROWS_CAP, DEFAULT_TIMEOUT_MS)
        names = [c["name"] for c in res.columns]
        return [dict(zip(names, row, strict=False)) for row in res.rows]


class _Cursor:
    """Run a DB-API cursor and shape the result; the driver applies its timeout around it."""

    @staticmethod
    def run(
        conn: Any, sql: str, params: Any, max_rows: int, column_type: Any, mysql: bool, command_hint: str | None = None
    ) -> QueryResult:
        started = time.perf_counter()
        cur = conn.cursor()
        try:
            if params:
                cur.execute(sql, params)
            else:
                cur.execute(sql)
            if cur.description:
                raw = cur.fetchmany(max_rows + 1)
                truncated = len(raw) > max_rows
                rows = [[to_js(v) for v in r] for r in raw[:max_rows]]
                columns = [{"name": d[0], "type": column_type(d)} for d in cur.description]
                return QueryResult(
                    columns,
                    rows,
                    len(rows),
                    truncated,
                    int((time.perf_counter() - started) * 1000),
                    command_hint or command_of(sql, mysql),
                )
            affected = cur.rowcount if cur.rowcount is not None and cur.rowcount >= 0 else 0
            return QueryResult(
                [],
                [],
                affected,
                False,
                int((time.perf_counter() - started) * 1000),
                command_hint or command_of(sql, mysql),
            )
        finally:
            cur.close()
