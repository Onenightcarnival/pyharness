"""MySQL and MariaDB driver through PyMySQL."""

from __future__ import annotations

import re
from textwrap import dedent
from typing import Any

import pymysql

from pyharness import package_toml

from .driver import CONNECT_TIMEOUT_S, DEFAULT_TIMEOUT_MS, Driver, EngineError, QueryResult, SessionState, _Cursor

# field type code -> type name of result columns
MYSQL_TYPES: dict[int, str] = {int(code): name for code, name in package_toml(__file__)["mysql"]["types"].items()}


class MySQLDriver(Driver):
    kind = "mysql"
    mysql = True

    def __init__(self, host: str, port: int, database: str, user: str, password: str, ssl: bool) -> None:
        super().__init__()
        self.conn = pymysql.connect(
            host=host, port=port, user=user, password=password, database=database or None,
            connect_timeout=CONNECT_TIMEOUT_S, autocommit=True, ssl={"ssl": {}} if ssl else None, charset="utf8mb4",
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
        sql = dedent(
            """
            SELECT SCHEMA_NAME AS name FROM information_schema.SCHEMATA
            WHERE SCHEMA_NAME NOT IN ('information_schema','mysql','performance_schema','sys')
            ORDER BY (SCHEMA_NAME <> %s), SCHEMA_NAME
            """
        ).strip()
        return [r["name"] for r in self._rows(sql, [self.default_schema])]

    def list_tables(self, schema: str) -> list[dict[str, str]]:
        sql = dedent(
            """
            SELECT TABLE_NAME AS name, TABLE_TYPE AS type FROM information_schema.TABLES WHERE TABLE_SCHEMA = %s
            ORDER BY (TABLE_TYPE <> 'BASE TABLE'), TABLE_NAME
            """
        ).strip()
        rows = self._rows(sql, [schema])
        return [
            {
                "schema": schema,
                "name": r["name"],
                "kind": "view" if re.search("view", str(r["type"]), re.I) else "table",
            }
            for r in rows
        ]

    def columns(self, schema: str, table: str) -> list[dict[str, Any]]:
        sql = dedent(
            """
            SELECT ORDINAL_POSITION AS position, COLUMN_NAME AS name, COLUMN_TYPE AS type, IS_NULLABLE AS nullable,
            COLUMN_DEFAULT AS default_value, COLUMN_KEY AS col_key, EXTRA AS extra FROM information_schema.COLUMNS
            WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s ORDER BY ORDINAL_POSITION
            """
        ).strip()
        rows = self._rows(sql, [schema, table])
        out = []
        for r in rows:
            nullable = str(r["nullable"]).upper() == "YES"
            default = r["default_value"]
            if default is not None and str(default) == "NULL" and nullable:
                default = None
            typ = str(r["type"]) + (
                " AUTO_INCREMENT" if re.search("auto_increment", str(r["extra"] or ""), re.I) else ""
            )
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
        sql = dedent(
            """
            SELECT INDEX_NAME AS name, NON_UNIQUE AS non_unique, SEQ_IN_INDEX AS seq, COLUMN_NAME AS col
            FROM information_schema.STATISTICS
            WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s ORDER BY (INDEX_NAME <> 'PRIMARY'), INDEX_NAME, SEQ_IN_INDEX
            """
        ).strip()
        rows = self._rows(sql, [schema, table])
        grouped: dict[str, dict[str, Any]] = {}
        for r in rows:
            g = grouped.setdefault(
                r["name"],
                {
                    "name": r["name"],
                    "columns": [],
                    "unique": int(r["non_unique"]) == 0,
                    "primary": r["name"] == "PRIMARY",
                },
            )
            g["columns"].append(r["col"] if r["col"] is not None else f"expr#{r['seq']}")
        return list(grouped.values())

    def ddl(self, schema: str, table: str, kind: str) -> str:
        q = self.quote_ident
        res = self.query(
            f"SHOW CREATE {'VIEW' if kind == 'view' else 'TABLE'} {q(schema)}.{q(table)}", None, 1, DEFAULT_TIMEOUT_MS
        )
        if not res.rows:
            return ""
        names = [c["name"] for c in res.columns]
        for key in ("Create Table", "Create View"):
            if key in names:
                return str(res.rows[0][names.index(key)]) + ";"
        return str(res.rows[0][1]) + ";"

    def estimated_rows(self, schema: str, table: str) -> int | None:
        rows = self._rows(
            "SELECT TABLE_ROWS AS n FROM information_schema.TABLES WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s",
            [schema, table],
        )
        return int(rows[0]["n"]) if rows and rows[0]["n"] is not None else None

    def server_version(self) -> str:
        v = str(self._rows("SELECT VERSION() AS v")[0]["v"])
        return ("MariaDB " if "mariadb" in v.lower() else "MySQL ") + v[:60]

    def close(self) -> None:
        with self.lock:
            self.conn.close()
