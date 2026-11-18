from __future__ import annotations

import contextlib
import json
import re
from dataclasses import dataclass
from typing import Any

from .driver import (
    COUNT_TIMEOUT_MS,
    DEFAULT_MAX_ROWS,
    DEFAULT_TIMEOUT_MS,
    MAX_ROWS_CAP,
    Driver,
    EngineError,
    QueryResult,
)
from .sql import is_read_only, split_statements


def clamp(value: Any, lo: int, hi: int, default: int) -> int:
    try:
        v = int(value)
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, v))


@dataclass
class TableInfo:
    table: dict[str, str]
    columns: list[dict[str, Any]]
    indexes: list[dict[str, Any]]
    primary_key: list[str]
    estimated_rows: int | None = None

    def describe(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "table": self.table,
            "columns": self.columns,
            "indexes": self.indexes,
            "primaryKey": self.primary_key,
        }
        if self.estimated_rows is not None:
            out["estimatedRows"] = self.estimated_rows
        return out


def run_query(
    driver: Driver,
    sql: str,
    *,
    allow_write: bool,
    max_rows: int | None = None,
    timeout_ms: int | None = None,
    params: list[Any] | None = None,
) -> QueryResult:
    statements = split_statements(sql, driver.mysql)
    if not statements:
        raise EngineError("empty SQL")
    if len(statements) > 1:
        raise EngineError(f"one statement at a time (got {len(statements)}); run them separately or use a transaction")
    statement = statements[0]
    if not allow_write and not is_read_only(statement, driver.mysql):
        raise EngineError(
            "refused: only read statements run here (SELECT / WITH / EXPLAIN / SHOW); writes go through db_execute"
        )
    return driver.query(
        statement,
        params,
        clamp(max_rows, 1, MAX_ROWS_CAP, DEFAULT_MAX_ROWS),
        clamp(timeout_ms, 1, 600000, DEFAULT_TIMEOUT_MS),
    )


def table_info(driver: Driver, schema: str, name: str, kind: str = "table") -> TableInfo:
    cols = driver.columns(schema, name)
    idx = driver.indexes(schema, name)
    est = None
    with contextlib.suppress(Exception):
        est = driver.estimated_rows(schema, name)
    return TableInfo(
        {"schema": schema, "name": name, "kind": kind}, cols, idx, [c["name"] for c in cols if c["primaryKey"]], est
    )


FILTER_OPS = ("=", "!=", ">", ">=", "<", "<=", "like", "is null", "is not null")


def page_rows(
    driver: Driver,
    schema: str,
    table: str,
    *,
    offset: int = 0,
    limit: int = 100,
    sort: dict[str, Any] | None = None,
    filters: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    q = driver.quote_ident
    cols = driver.columns(schema, table)
    names = {c["name"] for c in cols}
    pk = [c["name"] for c in cols if c["primaryKey"]]
    where_parts: list[str] = []
    params: list[Any] = []
    for f in filters or []:
        col, op = f.get("column"), str(f.get("op", "=")).lower()
        if col not in names:
            raise EngineError(f"unknown column '{col}'")
        if op not in FILTER_OPS:
            raise EngineError(f"unsupported operator '{op}'")
        if op == "is null":
            where_parts.append(f"{q(col)} IS NULL")
        elif op == "is not null":
            where_parts.append(f"{q(col)} IS NOT NULL")
        else:
            params.append(str(f.get("value") if f.get("value") is not None else ""))
            ph = driver.placeholder(len(params))
            where_parts.append(f"{driver.cast_to_text(q(col))} LIKE {ph}" if op == "like" else f"{q(col)} {op} {ph}")
    where = (" WHERE " + " AND ".join(where_parts)) if where_parts else ""
    if sort and sort.get("column"):
        if sort["column"] not in names:
            raise EngineError(f"unknown column '{sort['column']}'")
        order = f" ORDER BY {q(sort['column'])} {'DESC' if sort.get('desc') else 'ASC'}"
    elif pk:
        order = " ORDER BY " + ", ".join(q(c) for c in pk)
    else:
        order = ""
    lim = clamp(limit, 1, 1000, 100)
    off = max(0, int(offset or 0))
    target = f"{q(schema)}.{q(table)}"
    res = driver.query(
        f"SELECT * FROM {target}{where}{order} LIMIT {lim} OFFSET {off}", params or None, lim, DEFAULT_TIMEOUT_MS
    )
    out = res.describe()
    try:
        count = driver.query(f"SELECT COUNT(*) AS n FROM {target}{where}", params or None, 1, COUNT_TIMEOUT_MS)
        if count.rows:
            out["total"] = int(count.rows[0][0])
    except Exception:  # noqa: BLE001
        pass
    out["primaryKey"] = pk
    return out


def grid_changes(driver: Driver, schema: str, table: str, changes: list[dict[str, Any]], apply: bool) -> dict[str, Any]:
    q = driver.quote_ident
    cols = driver.columns(schema, table)
    names = {c["name"] for c in cols}
    pk = [c["name"] for c in cols if c["primaryKey"]]
    target = f"{q(schema)}.{q(table)}"

    def key_clause(key: dict[str, Any]) -> str:
        if not pk:
            raise EngineError("table has no primary key; edit it with SQL instead")
        return " AND ".join(
            f"{q(k)} IS NULL" if key.get(k) is None else f"{q(k)} = {driver.literal(key.get(k))}" for k in pk
        )

    statements: list[str] = []
    for ch in changes:
        for k in list((ch.get("values") or {}).keys()) + list((ch.get("key") or {}).keys()):
            if k not in names:
                raise EngineError(f"unknown column '{k}'")
        kind = ch.get("kind")
        if kind == "update":
            sets = ", ".join(f"{q(k)} = {driver.literal(v)}" for k, v in (ch.get("values") or {}).items())
            if sets:
                statements.append(f"UPDATE {target} SET {sets} WHERE {key_clause(ch.get('key') or {})}")
        elif kind == "insert":
            values = {
                k: v for k, v in (ch.get("values") or {}).items() if v is not None or k in (ch.get("nulls") or [])
            }
            if not values:
                statements.append(driver.insert_defaults(target))
            else:
                statements.append(
                    f"INSERT INTO {target} ({', '.join(q(k) for k in values)}) "
                    f"VALUES ({', '.join(driver.literal(v) for v in values.values())})"
                )
        elif kind == "delete":
            statements.append(f"DELETE FROM {target} WHERE {key_clause(ch.get('key') or {})}")
        else:
            raise EngineError(f"unknown change kind '{kind}'")
    if not apply:
        return {"statements": statements, "applied": False}
    try:
        affected = driver.transaction([{"sql": s} for s in statements], DEFAULT_TIMEOUT_MS)
    except Exception as exc:  # noqa: BLE001
        return {"statements": statements, "applied": False, "error": str(exc).strip()}
    return {"statements": statements, "applied": True, "affected": affected}


def to_csv(result: QueryResult) -> str:
    def cell(v: Any) -> str:
        if v is None:
            return ""
        s = v if isinstance(v, str) else json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else str(v)
        return '"' + s.replace('"', '""') + '"' if re.search(r'[",\n\r]', s) else s

    lines = [",".join(cell(c["name"]) for c in result.columns)]
    lines += [",".join(cell(v) for v in row) for row in result.rows]
    return "\r\n".join(lines) + "\r\n"


def human_table(result: QueryResult) -> str:
    """The model-facing rendering of a result."""
    if not result.columns:
        return f"{result.command}: {result.row_count} row(s) affected ({result.duration_ms} ms)"

    def cell(v: Any) -> str:
        s = "NULL" if v is None else json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else str(v)
        return s if len(s) <= 80 else s[:77] + "…"

    names = [c["name"] for c in result.columns]
    rows = [[cell(v) for v in r] for r in result.rows]
    widths = [max([len(n)] + [len(r[i]) for r in rows]) for i, n in enumerate(names)]
    lines = [" | ".join(n.ljust(widths[i]) for i, n in enumerate(names)), "-+-".join("-" * w for w in widths)]
    lines += [" | ".join(c.ljust(widths[i]) for i, c in enumerate(r)) for r in rows]
    lines.append(
        f"({result.row_count} row(s){', truncated — add WHERE/LIMIT' if result.truncated else ''}, "
        f"{result.duration_ms} ms)"
    )
    return "\n".join(lines)
