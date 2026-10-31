"""Database engine: drivers (SQLite, PostgreSQL / GaussDB, MySQL / MariaDB), statement classification, paging,
grid changes and CSV. Drivers are synchronous DB-API connections; the service runs them in worker threads, one
statement at a time per connection.
"""

from __future__ import annotations

import datetime as dt
import decimal
import json
import random
import re
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from typing import Any

DEFAULT_MAX_ROWS = 1000
MAX_ROWS_CAP = 100000
DEFAULT_TIMEOUT_MS = 30000
COUNT_TIMEOUT_MS = 10000
CONNECT_TIMEOUT_S = 15
DEFAULT_PORT = {"sqlite": 0, "postgres": 5432, "gaussdb": 8000, "mysql": 3306}
KINDS = ("sqlite", "postgres", "gaussdb", "mysql")
TARGETS = ("any", "read-write", "read-only", "primary", "standby", "prefer-standby")


class EngineError(RuntimeError):
    pass


# ---------------------------------------------------------------------- statement classification
READ_START = re.compile(r"^(select|with|explain|show|values|table|describe|desc|pragma)\b", re.I)
DML_OR_DDL = re.compile(
    r"\b(insert|update|delete|merge|create|alter|drop|truncate|grant|revoke|vacuum|reindex|attach|detach|copy|call|lock|refresh"
    r"|cluster|reset|begin|commit|rollback|savepoint|release)\b",
    re.I,
)


def skeleton(sql: str, mysql: bool) -> str:
    """The statement without comments, literals and quoted identifiers."""
    s = re.sub(r"--[^\n]*", " ", sql)
    s = re.sub(r"/\*[\s\S]*?\*/", " ", s)
    if mysql:
        s = re.sub(r"#[^\n]*", " ", s)
        s = re.sub(r"'(?:[^'\\]|''|\\.)*'", "''", s)
        s = re.sub(r"`(?:[^`]|``)*`", "``", s)
    s = re.sub(r"'(?:[^']|'')*'", "''", s)
    s = re.sub(r'"(?:[^"]|"")*"', '""', s)
    s = re.sub(r"\$\$[\s\S]*?\$\$", "''", s)
    return s


def split_statements(sql: str, mysql: bool) -> list[str]:
    out: list[str] = []
    buf: list[str] = []
    i, n, depth = 0, len(sql), 0
    quote: str | None = None
    while i < n:
        c = sql[i]
        if quote:
            buf.append(c)
            if mysql and quote == "'" and c == "\\" and i + 1 < n:
                buf.append(sql[i + 1])
                i += 2
                continue
            if c == quote:
                if i + 1 < n and sql[i + 1] == quote:
                    buf.append(quote)
                    i += 2
                    continue
                quote = None
            i += 1
            continue
        if c in ("'", '"') or (mysql and c == "`"):
            quote = c
            buf.append(c)
        elif sql.startswith("--", i) or (mysql and c == "#"):
            end = sql.find("\n", i)
            end = n if end < 0 else end
            buf.append(sql[i:end])
            i = end
            continue
        elif sql.startswith("/*", i):
            end = sql.find("*/", i + 2)
            end = n if end < 0 else end + 2
            buf.append(sql[i:end])
            i = end
            continue
        elif c == "(":
            depth += 1
            buf.append(c)
        elif c == ")":
            depth = max(0, depth - 1)
            buf.append(c)
        elif c == ";" and depth == 0:
            out.append("".join(buf))
            buf = []
        else:
            buf.append(c)
        i += 1
    out.append("".join(buf))
    return [p.strip() for p in out if skeleton(p, mysql).strip()]


def is_read_only(statement: str, mysql: bool) -> bool:
    s = skeleton(statement, mysql).strip()
    m = READ_START.match(s)
    if not m:
        return False
    head = m.group(1).lower()
    rest = s[m.end() :]
    if head == "show":
        return True
    if head == "pragma":
        return "=" not in rest
    if head == "select" and re.search(r"\binto\b", rest, re.I):
        return False
    if re.search(r"\bfor\s+(update|share|no\s+key\s+update|key\s+share)\b", rest, re.I):
        return False
    return not DML_OR_DDL.search(rest)


def command_of(sql: str, mysql: bool) -> str:
    s = skeleton(sql, mysql).strip()
    m = re.match(r"[A-Za-z]+", s)
    return m.group(0).upper() if m else "SQL"


# ---------------------------------------------------------------------- values
def to_js(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, (bytes, bytearray, memoryview)):
        return {"$bytes": len(value)}
    if isinstance(value, decimal.Decimal):
        return str(value)
    if isinstance(value, (dt.datetime, dt.date, dt.time)):
        return value.isoformat()
    if isinstance(value, dt.timedelta):
        return str(value)
    if isinstance(value, (list, dict)):
        return value
    return str(value)


def sql_literal(value: Any, mysql: bool = False) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, (int, float)):
        return str(value)
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    if mysql:
        text = text.replace("\\", "\\\\").replace("'", "\\'").replace("\n", "\\n").replace("\r", "\\r").replace("\0", "\\0")
        return f"'{text}'"
    return "'" + text.replace("'", "''") + "'"


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
    def run(conn: Any, sql: str, params: Any, max_rows: int, column_type: Any, mysql: bool, command_hint: str | None = None) -> QueryResult:
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
                    columns, rows, len(rows), truncated, int((time.perf_counter() - started) * 1000), command_hint or command_of(sql, mysql)
                )
            affected = cur.rowcount if cur.rowcount is not None and cur.rowcount >= 0 else 0
            return QueryResult([], [], affected, False, int((time.perf_counter() - started) * 1000), command_hint or command_of(sql, mysql))
        finally:
            cur.close()


class SQLiteDriver(Driver):
    kind = "sqlite"

    def __init__(self, file: str) -> None:
        super().__init__()
        self.file = file
        self.conn = sqlite3.connect(file, check_same_thread=False, isolation_level=None)

    def query(self, sql: str, params: list[Any] | None, max_rows: int, timeout_ms: int) -> QueryResult:
        with self.lock:
            deadline = time.monotonic() + timeout_ms / 1000
            self.conn.set_progress_handler(lambda: 1 if time.monotonic() > deadline else 0, 10000)
            try:
                return _Cursor.run(self.conn, sql, params, max_rows, lambda d: "", False)
            except sqlite3.OperationalError as exc:
                if "interrupted" in str(exc):
                    raise EngineError(f"statement timed out after {timeout_ms} ms") from exc
                raise
            finally:
                self.conn.set_progress_handler(None, 0)

    def transaction(self, statements: list[dict[str, Any]], timeout_ms: int) -> int:
        with self.lock:
            self.conn.execute("BEGIN")
            try:
                total = 0
                for st in statements:
                    total += self.query(st["sql"], st.get("params"), 1, timeout_ms).row_count
                self.conn.execute("COMMIT")
                return total
            except Exception:
                self.conn.execute("ROLLBACK")
                raise

    def list_schemas(self) -> list[str]:
        return [r["name"] for r in self._rows("PRAGMA database_list")]

    def list_tables(self, schema: str) -> list[dict[str, str]]:
        q = self.quote_ident
        rows = self._rows(
            f"SELECT name, type FROM {q(schema)}.sqlite_master WHERE type IN ('table','view') AND name NOT LIKE 'sqlite_%' ORDER BY type, name"
        )
        return [{"schema": schema, "name": r["name"], "kind": "view" if r["type"] == "view" else "table"} for r in rows]

    def columns(self, schema: str, table: str) -> list[dict[str, Any]]:
        q = self.quote_ident
        rows = self._rows(f"PRAGMA {q(schema)}.table_info({q(table)})")
        return [
            {
                "name": r["name"],
                "type": r["type"] or "",
                "nullable": r["notnull"] == 0,
                "defaultValue": r["dflt_value"],
                "primaryKey": r["pk"] > 0,
                "position": r["cid"] + 1,
            }
            for r in rows
        ]

    def indexes(self, schema: str, table: str) -> list[dict[str, Any]]:
        q = self.quote_ident
        out = []
        for ix in self._rows(f"PRAGMA {q(schema)}.index_list({q(table)})"):
            cols = [c["name"] for c in self._rows(f"PRAGMA {q(schema)}.index_info({q(ix['name'])})")]
            out.append({"name": ix["name"], "columns": cols, "unique": ix["unique"] == 1, "primary": ix["origin"] == "pk"})
        return out

    def ddl(self, schema: str, table: str, kind: str) -> str:
        q = self.quote_ident
        parts = [r["sql"] + ";" for r in self._rows(f"SELECT sql FROM {q(schema)}.sqlite_master WHERE name = ?", [table]) if r["sql"]]
        parts += [
            r["sql"] + ";"
            for r in self._rows(
                f"SELECT sql FROM {q(schema)}.sqlite_master WHERE type = 'index' AND tbl_name = ? AND sql IS NOT NULL", [table]
            )
        ]
        return "\n".join(parts)

    def estimated_rows(self, schema: str, table: str) -> int | None:
        q = self.quote_ident
        return self._rows(f"SELECT count(*) AS n FROM {q(schema)}.{q(table)}")[0]["n"]

    def server_version(self) -> str:
        return "SQLite " + self._rows("SELECT sqlite_version() AS v")[0]["v"]

    def close(self) -> None:
        with self.lock:
            self.conn.close()


PG_TYPES = {
    16: "bool", 17: "bytea", 18: "char", 19: "name", 20: "int8", 21: "int2", 23: "int4", 25: "text", 26: "oid", 114: "json", 142: "xml",
    700: "float4", 701: "float8", 790: "money", 1042: "bpchar", 1043: "varchar", 1082: "date", 1083: "time", 1114: "timestamp",
    1184: "timestamptz", 1186: "interval", 1266: "timetz", 1700: "numeric", 2950: "uuid", 3802: "jsonb", 1007: "int4[]", 1009: "text[]", 1015: "varchar[]",
}  # fmt: skip


class PgDriver(Driver):
    """PostgreSQL and GaussDB through psycopg 3; `kind` tells them apart."""

    def __init__(self, kind: str, host: str, port: int, database: str, user: str, password: str, ssl: bool) -> None:
        super().__init__()
        import psycopg

        self.kind = kind
        self.conn = psycopg.connect(
            host=host, port=port, dbname=database, user=user, password=password, connect_timeout=CONNECT_TIMEOUT_S,
            application_name="pyharness-rdb", sslmode="require" if ssl else "prefer", autocommit=True,
        )  # fmt: skip
        self.node = f"{host}:{port}"
        self._database = database

    @property
    def default_schema(self) -> str:
        return "public"

    def placeholder(self, i: int) -> str:
        return "%s"

    def session_state(self) -> SessionState:
        r = self._rows("SELECT pg_is_in_recovery() AS in_recovery, current_setting('transaction_read_only') AS read_only")[0]
        return SessionState(r["in_recovery"] in (True, "t", "true"), str(r["read_only"]).lower() == "on")

    def _timeout(self, ms: int | None) -> None:
        try:
            self.conn.execute(f"SET statement_timeout = {int(ms)}" if ms else "SET statement_timeout = DEFAULT")
        except Exception:  # noqa: BLE001
            pass

    def query(self, sql: str, params: list[Any] | None, max_rows: int, timeout_ms: int) -> QueryResult:
        import psycopg

        with self.lock:
            self._timeout(timeout_ms)
            try:
                return _Cursor.run(self.conn, sql, params, max_rows, lambda d: PG_TYPES.get(d.type_code, f"oid:{d.type_code}"), False)
            except psycopg.OperationalError as exc:
                if self.conn.closed:
                    self.alive = False
                raise EngineError(str(exc).strip()) from exc
            except psycopg.Error as exc:
                detail = getattr(getattr(exc, "diag", None), "message_detail", None)
                raise EngineError(str(exc).strip() + (f" ({detail})" if detail else "")) from exc
            finally:
                self._timeout(None)

    def transaction(self, statements: list[dict[str, Any]], timeout_ms: int) -> int:
        with self.lock:
            self.conn.execute("BEGIN")
            try:
                total = sum(self.query(st["sql"], st.get("params"), 1, timeout_ms).row_count for st in statements)
                self.conn.execute("COMMIT")
                return total
            except Exception:
                try:
                    self.conn.execute("ROLLBACK")
                except Exception:  # noqa: BLE001
                    pass
                raise

    def list_schemas(self) -> list[str]:
        return [
            r["nspname"]
            for r in self._rows(
                "SELECT nspname FROM pg_namespace WHERE nspname NOT IN ('pg_catalog','information_schema','pg_toast') "
                "AND nspname NOT LIKE 'pg_temp%' AND nspname NOT LIKE 'pg_toast%' ORDER BY (nspname <> 'public'), nspname"
            )
        ]

    def list_tables(self, schema: str) -> list[dict[str, str]]:
        rows = self._rows(
            "SELECT c.relname AS name, c.relkind AS kind FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE n.nspname = %s AND c.relkind IN ('r','p','v','m','f') ORDER BY (c.relkind IN ('v','m')), c.relname",
            [schema],
        )
        return [{"schema": schema, "name": r["name"], "kind": "view" if r["kind"] in ("v", "m") else "table"} for r in rows]

    def columns(self, schema: str, table: str) -> list[dict[str, Any]]:
        rows = self._rows(
            "SELECT a.attnum AS position, a.attname AS name, format_type(a.atttypid, a.atttypmod) AS type, NOT a.attnotnull AS nullable, "
            "pg_get_expr(d.adbin, d.adrelid) AS default_value, "
            "EXISTS (SELECT 1 FROM pg_index i WHERE i.indrelid = c.oid AND i.indisprimary AND a.attnum = ANY(i.indkey)) AS primary_key "
            "FROM pg_attribute a JOIN pg_class c ON c.oid = a.attrelid JOIN pg_namespace n ON n.oid = c.relnamespace "
            "LEFT JOIN pg_attrdef d ON d.adrelid = c.oid AND d.adnum = a.attnum "
            "WHERE n.nspname = %s AND c.relname = %s AND a.attnum > 0 AND NOT a.attisdropped ORDER BY a.attnum",
            [schema, table],
        )
        return [
            {
                "name": r["name"],
                "type": r["type"],
                "nullable": bool(r["nullable"]),
                "defaultValue": r["default_value"],
                "primaryKey": bool(r["primary_key"]),
                "position": r["position"],
            }
            for r in rows
        ]

    def indexes(self, schema: str, table: str) -> list[dict[str, Any]]:
        rows = self._rows(
            'SELECT ic.relname AS name, i.indisunique AS "unique", i.indisprimary AS "primary", i.indkey::text AS keys '
            "FROM pg_index i JOIN pg_class c ON c.oid = i.indrelid JOIN pg_class ic ON ic.oid = i.indexrelid JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE n.nspname = %s AND c.relname = %s ORDER BY i.indisprimary DESC, ic.relname",
            [schema, table],
        )
        names = {
            r["attnum"]: r["name"]
            for r in self._rows(
                "SELECT a.attnum, a.attname::text AS name FROM pg_attribute a JOIN pg_class c ON c.oid = a.attrelid JOIN pg_namespace n ON n.oid = c.relnamespace "
                "WHERE n.nspname = %s AND c.relname = %s AND a.attnum > 0 AND NOT a.attisdropped",
                [schema, table],
            )
        }
        out = []
        for r in rows:
            keys = [int(k) for k in str(r["keys"]).split()]
            out.append(
                {
                    "name": r["name"],
                    "columns": [names.get(k, f"expr#{k}") for k in keys],
                    "unique": bool(r["unique"]),
                    "primary": bool(r["primary"]),
                }
            )
        return out

    def ddl(self, schema: str, table: str, kind: str) -> str:
        q = self.quote_ident
        if kind == "view":
            d = self._rows("SELECT pg_get_viewdef((%s || '.' || %s)::regclass, true) AS def", [q(schema), q(table)])[0]["def"]
            return f"CREATE OR REPLACE VIEW {q(schema)}.{q(table)} AS\n{d}"
        cols = self.columns(schema, table)
        lines = [
            f"  {q(c['name'])} {c['type']}"
            + ("" if c["nullable"] else " NOT NULL")
            + (f" DEFAULT {c['defaultValue']}" if c["defaultValue"] else "")
            for c in cols
        ]
        pk = [c["name"] for c in cols if c["primaryKey"]]
        if pk:
            lines.append("  PRIMARY KEY (" + ", ".join(q(c) for c in pk) + ")")
        out = [f"CREATE TABLE {q(schema)}.{q(table)} (\n" + ",\n".join(lines) + "\n);"]
        out += [
            r["indexdef"] + ";"
            for r in self._rows(
                "SELECT indexdef FROM pg_indexes WHERE schemaname = %s AND tablename = %s AND indexname NOT IN "
                "(SELECT ic.relname FROM pg_index i JOIN pg_class ic ON ic.oid = i.indexrelid WHERE i.indisprimary)",
                [schema, table],
            )
        ]
        return "\n".join(out)

    def estimated_rows(self, schema: str, table: str) -> int | None:
        rows = self._rows(
            "SELECT c.reltuples::bigint AS n FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace WHERE n.nspname = %s AND c.relname = %s",
            [schema, table],
        )
        n = rows[0]["n"] if rows else None
        return None if n is None or int(n) < 0 else int(n)

    def server_version(self) -> str:
        v = str(self._rows("SELECT version() AS v")[0]["v"])
        if self.kind == "gaussdb":
            return v[:80]
        m = re.match(r"^PostgreSQL [^ ]+", v)
        return m.group(0) if m else v[:80]

    def close(self) -> None:
        with self.lock:
            self.conn.close()


MYSQL_TYPES = {
    0: "decimal", 1: "tinyint", 2: "smallint", 3: "int", 4: "float", 5: "double", 6: "null", 7: "timestamp", 8: "bigint", 9: "mediumint",
    10: "date", 11: "time", 12: "datetime", 13: "year", 14: "date", 15: "varchar", 16: "bit", 245: "json", 246: "decimal", 247: "enum",
    248: "set", 249: "tinyblob", 250: "mediumblob", 251: "longblob", 252: "blob", 253: "varchar", 254: "char", 255: "geometry",
}  # fmt: skip


class MySQLDriver(Driver):
    kind = "mysql"
    mysql = True

    def __init__(self, host: str, port: int, database: str, user: str, password: str, ssl: bool) -> None:
        super().__init__()
        import pymysql

        self.conn = pymysql.connect(
            host=host, port=port, user=user, password=password, database=database or None, connect_timeout=CONNECT_TIMEOUT_S,
            autocommit=True, ssl={"ssl": {}} if ssl else None, charset="utf8mb4",
        )  # fmt: skip
        self.node = f"{host}:{port}"
        self._database = database

    @property
    def default_schema(self) -> str:
        return self._database

    def quote_ident(self, name: str) -> str:
        return "`" + name.replace("`", "``") + "`"

    def placeholder(self, i: int) -> str:
        return "%s"

    def cast_to_text(self, expr: str) -> str:
        return f"CAST({expr} AS CHAR)"

    def insert_defaults(self, target: str) -> str:
        return f"INSERT INTO {target} () VALUES ()"

    def _flag(self, sql: str) -> bool:
        try:
            rows = self.query(sql, None, 1, DEFAULT_TIMEOUT_MS).rows
            return bool(rows and rows[0] and int(rows[0][0]) == 1)
        except Exception:  # noqa: BLE001
            return False

    def session_state(self) -> SessionState:
        read_only = self._flag("SELECT @@global.read_only") or self._flag("SELECT @@global.super_read_only")
        in_recovery = read_only
        for sql in ("SHOW REPLICA STATUS", "SHOW SLAVE STATUS"):
            try:
                in_recovery = len(self.query(sql, None, 10, DEFAULT_TIMEOUT_MS).rows) > 0
                break
            except Exception:  # noqa: BLE001
                continue
        return SessionState(in_recovery, read_only)

    def _timeout(self, ms: int | None) -> None:
        for sql in (
            f"SET SESSION max_execution_time = {int(ms)}" if ms else "SET SESSION max_execution_time = DEFAULT",
            f"SET SESSION max_statement_time = {ms / 1000:.3f}" if ms else "SET SESSION max_statement_time = DEFAULT",
        ):
            try:
                self.conn.cursor().execute(sql)
                return
            except Exception:  # noqa: BLE001
                continue

    @staticmethod
    def _type(d: Any) -> str:
        code, flags = d[1], d[7] if len(d) > 7 else 0
        binary = bool(flags & 128) if isinstance(flags, int) else False
        if code == 252 and not binary:
            return "text"
        if code == 253 and binary:
            return "varbinary"
        if code == 254 and binary:
            return "binary"
        return MYSQL_TYPES.get(code, f"type:{code}")

    def query(self, sql: str, params: list[Any] | None, max_rows: int, timeout_ms: int) -> QueryResult:
        import pymysql

        with self.lock:
            self._timeout(timeout_ms)
            try:
                return _Cursor.run(self.conn, sql, params, max_rows, self._type, True)
            except pymysql.err.OperationalError as exc:
                if not self.conn.open:
                    self.alive = False
                raise EngineError(str(exc.args[1] if len(exc.args) > 1 else exc)) from exc
            except pymysql.err.MySQLError as exc:
                raise EngineError(str(exc.args[1] if len(exc.args) > 1 else exc)) from exc
            finally:
                self._timeout(None)

    def transaction(self, statements: list[dict[str, Any]], timeout_ms: int) -> int:
        with self.lock:
            self.conn.cursor().execute("START TRANSACTION")
            try:
                total = sum(self.query(st["sql"], st.get("params"), 1, timeout_ms).row_count for st in statements)
                self.conn.cursor().execute("COMMIT")
                return total
            except Exception:
                try:
                    self.conn.cursor().execute("ROLLBACK")
                except Exception:  # noqa: BLE001
                    pass
                raise

    def list_schemas(self) -> list[str]:
        return [
            r["name"]
            for r in self._rows(
                "SELECT SCHEMA_NAME AS name FROM information_schema.SCHEMATA WHERE SCHEMA_NAME NOT IN ('information_schema','mysql','performance_schema','sys') "
                "ORDER BY (SCHEMA_NAME <> %s), SCHEMA_NAME",
                [self.default_schema],
            )
        ]

    def list_tables(self, schema: str) -> list[dict[str, str]]:
        rows = self._rows(
            "SELECT TABLE_NAME AS name, TABLE_TYPE AS type FROM information_schema.TABLES WHERE TABLE_SCHEMA = %s ORDER BY (TABLE_TYPE <> 'BASE TABLE'), TABLE_NAME",
            [schema],
        )
        return [{"schema": schema, "name": r["name"], "kind": "view" if re.search("view", str(r["type"]), re.I) else "table"} for r in rows]

    def columns(self, schema: str, table: str) -> list[dict[str, Any]]:
        rows = self._rows(
            "SELECT ORDINAL_POSITION AS position, COLUMN_NAME AS name, COLUMN_TYPE AS type, IS_NULLABLE AS nullable, COLUMN_DEFAULT AS default_value, "
            "COLUMN_KEY AS col_key, EXTRA AS extra FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s ORDER BY ORDINAL_POSITION",
            [schema, table],
        )
        out = []
        for r in rows:
            nullable = str(r["nullable"]).upper() == "YES"
            default = r["default_value"]
            if default is not None and str(default) == "NULL" and nullable:
                default = None
            typ = str(r["type"]) + (" AUTO_INCREMENT" if re.search("auto_increment", str(r["extra"] or ""), re.I) else "")
            out.append(
                {
                    "name": r["name"],
                    "type": typ,
                    "nullable": nullable,
                    "defaultValue": default,
                    "primaryKey": r["col_key"] == "PRI",
                    "position": int(r["position"]),
                }
            )
        return out

    def indexes(self, schema: str, table: str) -> list[dict[str, Any]]:
        rows = self._rows(
            "SELECT INDEX_NAME AS name, NON_UNIQUE AS non_unique, SEQ_IN_INDEX AS seq, COLUMN_NAME AS col FROM information_schema.STATISTICS "
            "WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s ORDER BY (INDEX_NAME <> 'PRIMARY'), INDEX_NAME, SEQ_IN_INDEX",
            [schema, table],
        )
        grouped: dict[str, dict[str, Any]] = {}
        for r in rows:
            g = grouped.setdefault(
                r["name"], {"name": r["name"], "columns": [], "unique": int(r["non_unique"]) == 0, "primary": r["name"] == "PRIMARY"}
            )
            g["columns"].append(r["col"] if r["col"] is not None else f"expr#{r['seq']}")
        return list(grouped.values())

    def ddl(self, schema: str, table: str, kind: str) -> str:
        q = self.quote_ident
        res = self.query(f"SHOW CREATE {'VIEW' if kind == 'view' else 'TABLE'} {q(schema)}.{q(table)}", None, 1, DEFAULT_TIMEOUT_MS)
        if not res.rows:
            return ""
        names = [c["name"] for c in res.columns]
        for key in ("Create Table", "Create View"):
            if key in names:
                return str(res.rows[0][names.index(key)]) + ";"
        return str(res.rows[0][1]) + ";"

    def estimated_rows(self, schema: str, table: str) -> int | None:
        rows = self._rows(
            "SELECT TABLE_ROWS AS n FROM information_schema.TABLES WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s", [schema, table]
        )
        return int(rows[0]["n"]) if rows and rows[0]["n"] is not None else None

    def server_version(self) -> str:
        v = str(self._rows("SELECT VERSION() AS v")[0]["v"])
        return ("MariaDB " if "mariadb" in v.lower() else "MySQL ") + v[:60]

    def close(self) -> None:
        with self.lock:
            self.conn.close()


def connect(profile: dict[str, Any], password: str) -> Driver:
    """Open a connection for a profile; network kinds try the hosts in order (target_session_attrs, load balancing)."""
    kind = profile["kind"]
    if kind == "sqlite":
        return SQLiteDriver(profile["file"])
    hosts = parse_hosts(profile["host"])
    if profile.get("loadBalanceHosts"):
        hosts = hosts[:]
        random.shuffle(hosts)
    target = profile.get("targetSessionAttrs") or "any"
    passes = ["standby", "any"] if target == "prefer-standby" else [target]
    failures: list[str] = []
    for want in passes:
        for host in hosts:
            port = int(profile["port"])
            try:
                if kind == "mysql":
                    driver: Driver = MySQLDriver(host, port, profile["database"], profile["user"], password, bool(profile.get("ssl")))
                else:
                    driver = PgDriver(kind, host, port, profile["database"], profile["user"], password, bool(profile.get("ssl")))
            except Exception as exc:  # noqa: BLE001
                failures.append(f"{host}:{port}: {str(exc).strip()}")
                continue
            if want == "any":
                return driver
            try:
                state = driver.session_state()  # type: ignore[attr-defined]
            except Exception as exc:  # noqa: BLE001
                driver.close()
                failures.append(f"{host}:{port}: {str(exc).strip()}")
                continue
            if session_matches(want, state):
                return driver
            driver.close()
            failures.append(f"{host}:{port}: session does not satisfy '{want}'")
    raise EngineError(f"no node accepted the connection (target {target}): {'; '.join(failures)}")


# ---------------------------------------------------------------------- engine-level operations
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
        out: dict[str, Any] = {"table": self.table, "columns": self.columns, "indexes": self.indexes, "primaryKey": self.primary_key}
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
        raise EngineError("refused: only read statements run here (SELECT / WITH / EXPLAIN / SHOW); writes go through db_execute")
    return driver.query(
        statement, params, clamp(max_rows, 1, MAX_ROWS_CAP, DEFAULT_MAX_ROWS), clamp(timeout_ms, 1, 600000, DEFAULT_TIMEOUT_MS)
    )


def table_info(driver: Driver, schema: str, name: str, kind: str = "table") -> TableInfo:
    cols = driver.columns(schema, name)
    idx = driver.indexes(schema, name)
    est = None
    try:
        est = driver.estimated_rows(schema, name)
    except Exception:  # noqa: BLE001
        pass
    return TableInfo({"schema": schema, "name": name, "kind": kind}, cols, idx, [c["name"] for c in cols if c["primaryKey"]], est)


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
    res = driver.query(f"SELECT * FROM {target}{where}{order} LIMIT {lim} OFFSET {off}", params or None, lim, DEFAULT_TIMEOUT_MS)
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
        return " AND ".join(f"{q(k)} IS NULL" if key.get(k) is None else f"{q(k)} = {driver.literal(key.get(k))}" for k in pk)

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
            values = {k: v for k, v in (ch.get("values") or {}).items() if v is not None or k in (ch.get("nulls") or [])}
            if not values:
                statements.append(driver.insert_defaults(target))
            else:
                statements.append(
                    f"INSERT INTO {target} ({', '.join(q(k) for k in values)}) VALUES ({', '.join(driver.literal(v) for v in values.values())})"
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
    lines.append(f"({result.row_count} row(s){', truncated — add WHERE/LIMIT' if result.truncated else ''}, {result.duration_ms} ms)")
    return "\n".join(lines)


@dataclass
class Pool:
    """One live driver per profile id; reopened when the profile changed or the connection died; idle ones closed."""

    idle_close_s: float = 600.0
    drivers: dict[str, tuple[Driver, int]] = field(default_factory=dict)
    lock: threading.Lock = field(default_factory=threading.Lock)

    def get(self, profile: dict[str, Any], password: str) -> Driver:
        pid = profile["id"]
        with self.lock:
            entry = self.drivers.get(pid)
            if entry and entry[1] == profile.get("updatedAt") and entry[0].alive:
                entry[0].last_used = time.monotonic()
                return entry[0]
            if entry:
                try:
                    entry[0].close()
                except Exception:  # noqa: BLE001
                    pass
            driver = connect(profile, password)
            self.drivers[pid] = (driver, int(profile.get("updatedAt") or 0))
            return driver

    def drop(self, pid: str) -> None:
        with self.lock:
            entry = self.drivers.pop(pid, None)
        if entry:
            try:
                entry[0].close()
            except Exception:  # noqa: BLE001
                pass

    def sweep(self) -> None:
        now = time.monotonic()
        with self.lock:
            stale = [pid for pid, (d, _) in self.drivers.items() if now - d.last_used > self.idle_close_s]
        for pid in stale:
            self.drop(pid)

    def close_all(self) -> None:
        for pid in list(self.drivers):
            self.drop(pid)
