"""PostgreSQL and GaussDB driver through psycopg 3."""

from __future__ import annotations

import re
from textwrap import dedent
from typing import Any

import psycopg

from pyharness import package_toml

from .driver import CONNECT_TIMEOUT_S, Driver, EngineError, QueryResult, SessionState, _Cursor

# pg_type oid -> type name of result columns
PG_TYPES: dict[int, str] = {int(oid): name for oid, name in package_toml(__file__)["postgres"]["types"].items()}


class PgDriver(Driver):
    """PostgreSQL and GaussDB through psycopg 3; `kind` tells them apart."""

    def __init__(self, kind: str, host: str, port: int, database: str, user: str, password: str, ssl: bool) -> None:
        super().__init__()
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
        r = self._rows(
            "SELECT pg_is_in_recovery() AS in_recovery, current_setting('transaction_read_only') AS read_only"
        )[0]
        return SessionState(r["in_recovery"] in (True, "t", "true"), str(r["read_only"]).lower() == "on")

    def _timeout(self, ms: int | None) -> None:
        try:
            self.conn.execute(f"SET statement_timeout = {int(ms)}" if ms else "SET statement_timeout = DEFAULT")
        except Exception:  # noqa: BLE001
            pass

    def query(self, sql: str, params: list[Any] | None, max_rows: int, timeout_ms: int) -> QueryResult:
        with self.lock:
            self._timeout(timeout_ms)
            try:
                return _Cursor.run(
                    self.conn, sql, params, max_rows, lambda d: PG_TYPES.get(d.type_code, f"oid:{d.type_code}"), False
                )
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
        sql = dedent(
            """
            SELECT nspname FROM pg_namespace WHERE nspname NOT IN ('pg_catalog','information_schema','pg_toast')
            AND nspname NOT LIKE 'pg_temp%' AND nspname NOT LIKE 'pg_toast%'
            ORDER BY (nspname <> 'public'), nspname
            """
        ).strip()
        return [r["nspname"] for r in self._rows(sql)]

    def list_tables(self, schema: str) -> list[dict[str, str]]:
        sql = dedent(
            """
            SELECT c.relname AS name, c.relkind AS kind FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = %s AND c.relkind IN ('r','p','v','m','f') ORDER BY (c.relkind IN ('v','m')), c.relname
            """
        ).strip()
        rows = self._rows(sql, [schema])
        return [
            {"schema": schema, "name": r["name"], "kind": "view" if r["kind"] in ("v", "m") else "table"} for r in rows
        ]

    def columns(self, schema: str, table: str) -> list[dict[str, Any]]:
        sql = dedent(
            """
            SELECT a.attnum AS position, a.attname AS name, format_type(a.atttypid, a.atttypmod) AS type,
            NOT a.attnotnull AS nullable, pg_get_expr(d.adbin, d.adrelid) AS default_value,
            EXISTS (SELECT 1 FROM pg_index i WHERE i.indrelid = c.oid AND i.indisprimary
            AND a.attnum = ANY(i.indkey)) AS primary_key
            FROM pg_attribute a JOIN pg_class c ON c.oid = a.attrelid JOIN pg_namespace n ON n.oid = c.relnamespace
            LEFT JOIN pg_attrdef d ON d.adrelid = c.oid AND d.adnum = a.attnum
            WHERE n.nspname = %s AND c.relname = %s AND a.attnum > 0 AND NOT a.attisdropped ORDER BY a.attnum
            """
        ).strip()
        rows = self._rows(sql, [schema, table])
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
        index_sql = dedent(
            """
            SELECT ic.relname AS name, i.indisunique AS "unique", i.indisprimary AS "primary", i.indkey::text AS keys
            FROM pg_index i JOIN pg_class c ON c.oid = i.indrelid JOIN pg_class ic ON ic.oid = i.indexrelid
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = %s AND c.relname = %s ORDER BY i.indisprimary DESC, ic.relname
            """
        ).strip()
        attnum_sql = dedent(
            """
            SELECT a.attnum, a.attname::text AS name FROM pg_attribute a JOIN pg_class c ON c.oid = a.attrelid
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = %s AND c.relname = %s AND a.attnum > 0 AND NOT a.attisdropped
            """
        ).strip()
        rows = self._rows(index_sql, [schema, table])
        names = {r["attnum"]: r["name"] for r in self._rows(attnum_sql, [schema, table])}
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
            d = self._rows("SELECT pg_get_viewdef((%s || '.' || %s)::regclass, true) AS def", [q(schema), q(table)])[0][
                "def"
            ]
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
        index_sql = dedent(
            """
            SELECT indexdef FROM pg_indexes WHERE schemaname = %s AND tablename = %s AND indexname NOT IN
            (SELECT ic.relname FROM pg_index i JOIN pg_class ic ON ic.oid = i.indexrelid WHERE i.indisprimary)
            """
        ).strip()
        out += [r["indexdef"] + ";" for r in self._rows(index_sql, [schema, table])]
        return "\n".join(out)

    def estimated_rows(self, schema: str, table: str) -> int | None:
        sql = dedent(
            """
            SELECT c.reltuples::bigint AS n FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = %s AND c.relname = %s
            """
        ).strip()
        rows = self._rows(sql, [schema, table])
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
