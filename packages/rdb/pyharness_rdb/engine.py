"""Database engine facade: drivers (SQLite, PostgreSQL / GaussDB, MySQL / MariaDB), statement classification, paging,
grid changes and CSV, re-exported from :mod:`.sql`, :mod:`.driver`, :mod:`.sqlite`, :mod:`.postgres`, :mod:`.mysql`,
:mod:`.pool` and :mod:`.query`."""

from __future__ import annotations

from .driver import (
    CONNECT_TIMEOUT_S,
    COUNT_TIMEOUT_MS,
    DEFAULT_MAX_ROWS,
    DEFAULT_PORT,
    DEFAULT_TIMEOUT_MS,
    KINDS,
    MAX_ROWS_CAP,
    TARGETS,
    Driver,
    EngineError,
    QueryResult,
    SessionState,
    host_entries,
    parse_hosts,
    session_matches,
)
from .mysql import MYSQL_TYPES, MySQLDriver
from .pool import Pool, connect
from .postgres import PG_TYPES, PgDriver
from .query import FILTER_OPS, TableInfo, clamp, grid_changes, human_table, page_rows, run_query, table_info, to_csv
from .sql import DML_OR_DDL, READ_START, command_of, is_read_only, skeleton, split_statements, sql_literal, to_js
from .sqlite import SQLiteDriver

__all__ = [
    "CONNECT_TIMEOUT_S",
    "COUNT_TIMEOUT_MS",
    "DEFAULT_MAX_ROWS",
    "DEFAULT_PORT",
    "DEFAULT_TIMEOUT_MS",
    "DML_OR_DDL",
    "FILTER_OPS",
    "KINDS",
    "MAX_ROWS_CAP",
    "MYSQL_TYPES",
    "PG_TYPES",
    "READ_START",
    "TARGETS",
    "Driver",
    "EngineError",
    "MySQLDriver",
    "PgDriver",
    "Pool",
    "QueryResult",
    "SQLiteDriver",
    "SessionState",
    "TableInfo",
    "clamp",
    "command_of",
    "connect",
    "grid_changes",
    "host_entries",
    "human_table",
    "is_read_only",
    "page_rows",
    "parse_hosts",
    "run_query",
    "session_matches",
    "skeleton",
    "split_statements",
    "sql_literal",
    "table_info",
    "to_csv",
    "to_js",
]
