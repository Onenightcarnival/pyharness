"""SQLite driver (stdlib ``sqlite3``); statement timeouts through the progress handler."""

from __future__ import annotations

import sqlite3
import time
from typing import Any

from .driver import Driver, EngineError, QueryResult, _Cursor


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
            f"SELECT name, type FROM {q(schema)}.sqlite_master WHERE type IN ('table','view') "
            "AND name NOT LIKE 'sqlite_%' ORDER BY type, name"
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
            out.append(
                {"name": ix["name"], "columns": cols, "unique": ix["unique"] == 1, "primary": ix["origin"] == "pk"}
            )
        return out

    def ddl(self, schema: str, table: str, kind: str) -> str:
        q = self.quote_ident
        parts = [
            r["sql"] + ";"
            for r in self._rows(f"SELECT sql FROM {q(schema)}.sqlite_master WHERE name = ?", [table])
            if r["sql"]
        ]
        parts += [
            r["sql"] + ";"
            for r in self._rows(
                f"SELECT sql FROM {q(schema)}.sqlite_master WHERE type = 'index' AND tbl_name = ? AND sql IS NOT NULL",
                [table],
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
