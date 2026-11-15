"""
Statement text: classification (read-only or not), splitting on top-level semicolons, SQL literals and
JSON-safe values. ``mysql`` selects the MySQL dialect (backtick identifiers, backslash escapes, ``#`` comments).
"""

from __future__ import annotations

import datetime as dt
import decimal
import json
import re
from typing import Any

# ---------------------------------------------------------------------- statement classification
READ_START = re.compile(r"^(select|with|explain|show|values|table|describe|desc|pragma)\b", re.IGNORECASE)
DML_OR_DDL = re.compile(
    r"\b(insert|update|delete|merge|create|alter|drop|truncate|grant|revoke|vacuum|reindex|attach|detach|copy|call|lock|refresh"
    r"|cluster|reset|begin|commit|rollback|savepoint|release)\b",
    re.IGNORECASE,
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
    return re.sub(r"\$\$[\s\S]*?\$\$", "''", s)


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
    if head == "select" and re.search(r"\binto\b", rest, re.IGNORECASE):
        return False
    if re.search(r"\bfor\s+(update|share|no\s+key\s+update|key\s+share)\b", rest, re.IGNORECASE):
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
        text = (
            text.replace("\\", "\\\\")
            .replace("'", "\\'")
            .replace("\n", "\\n")
            .replace("\r", "\\r")
            .replace("\0", "\\0")
        )
        return f"'{text}'"
    return "'" + text.replace("'", "''") + "'"
