"""
Per-request usage ledger in SQLite with range aggregates by model and key.

| name                 | contract                                                                         |
|----------------------|----------------------------------------------------------------------------------|
| ``UsageStore``       | ledger bound to one file, opened on first use; rows past the retention are deleted on insert |
| ``record()``         | one finished gateway request                                                     |
| ``summary()``        | facets of the whole range; totals, groups and the newest rows of the filtered part |
| ``parse_filter()``   | row filter from query parameters; empty and unknown values are ignored           |
| ``range_start()``    | start of ``today`` (local midnight), ``7d`` or ``30d`` in epoch milliseconds     |

Cost is the sum over rows whose model has a price; ``None`` when no row of the group has one.
"""

from __future__ import annotations

import sqlite3
import time
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from textwrap import dedent
from typing import Any

from pyharness import package_toml

_CFG = package_toml(__file__)["usage"]
DETAIL_LIMIT: int = _CFG["DETAIL_LIMIT"]
RETENTION_MS: int = _CFG["RETENTION_DAYS"] * 24 * 60 * 60_000
RANGES = ("today", "7d", "30d")
PROTOCOLS = ("chat", "responses", "messages")
DAY_MS = 24 * 60 * 60_000

SCHEMA = dedent(
    """
    CREATE TABLE IF NOT EXISTS requests (
      id INTEGER PRIMARY KEY,
      time INTEGER NOT NULL,
      key_id TEXT NOT NULL,
      key_name TEXT NOT NULL,
      protocol TEXT NOT NULL,
      provider TEXT NOT NULL,
      model TEXT NOT NULL,
      model_id TEXT NOT NULL,
      stream INTEGER NOT NULL,
      input_tokens INTEGER NOT NULL DEFAULT 0,
      output_tokens INTEGER NOT NULL DEFAULT 0,
      cache_read_tokens INTEGER NOT NULL DEFAULT 0,
      cache_write_tokens INTEGER NOT NULL DEFAULT 0,
      reasoning_tokens INTEGER NOT NULL DEFAULT 0,
      ttft_ms INTEGER,
      duration_ms INTEGER NOT NULL,
      status INTEGER NOT NULL,
      error_code TEXT
    );
    CREATE INDEX IF NOT EXISTS requests_time ON requests (time);
    """
).strip()

INSERT = dedent(
    """
    INSERT INTO requests (
      time, key_id, key_name, protocol, provider, model, model_id, stream, input_tokens, output_tokens,
      cache_read_tokens, cache_write_tokens, reasoning_tokens, ttft_ms, duration_ms, status, error_code
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """
).strip()

# Ledger column → field of a recorded request and of a detail row.
FIELDS = {
    "time": "time",
    "key_id": "keyId",
    "key_name": "keyName",
    "protocol": "protocol",
    "provider": "provider",
    "model": "model",
    "model_id": "modelId",
    "stream": "stream",
    "input_tokens": "inputTokens",
    "output_tokens": "outputTokens",
    "cache_read_tokens": "cacheReadTokens",
    "cache_write_tokens": "cacheWriteTokens",
    "reasoning_tokens": "reasoningTokens",
    "ttft_ms": "ttftMs",
    "duration_ms": "durationMs",
    "status": "status",
    "error_code": "errorCode",
}


def now_ms() -> int:
    return int(time.time() * 1000)


def range_start(range_id: str, now: int | None = None) -> int:
    now = now_ms() if now is None else now
    if range_id == "today":
        midnight = datetime.fromtimestamp(now / 1000).replace(hour=0, minute=0, second=0, microsecond=0)
        return int(midnight.timestamp() * 1000)
    return now - (7 if range_id == "7d" else 30) * DAY_MS


def parse_filter(params: Mapping[str, str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for name, field in (("key", "keyId"), ("model", "modelId")):
        value = (params.get(name) or "").strip()
        if value and len(value) <= 253:
            out[field] = value
    if params.get("protocol") in PROTOCOLS:
        out["protocol"] = params["protocol"]
    if params.get("outcome") in ("ok", "error"):
        out["outcome"] = params["outcome"]
    return out


def _matches(row: sqlite3.Row, row_filter: Mapping[str, str]) -> bool:
    for field, column in (("keyId", "key_id"), ("modelId", "model_id"), ("protocol", "protocol")):
        if field in row_filter and row[column] != row_filter[field]:
            return False
    failed = row["status"] >= 400
    return not (row_filter.get("outcome") == "ok" and failed) and not (
        row_filter.get("outcome") == "error" and not failed
    )


def _totals() -> dict[str, Any]:
    return {
        "requests": 0,
        "errors": 0,
        "inputTokens": 0,
        "outputTokens": 0,
        "cacheReadTokens": 0,
        "reasoningTokens": 0,
        "cost": None,
    }


def _add(totals: dict[str, Any], row: sqlite3.Row, pricing: Mapping[str, Mapping[str, float]]) -> None:
    totals["requests"] += 1
    totals["errors"] += row["status"] >= 400
    totals["inputTokens"] += row["input_tokens"]
    totals["outputTokens"] += row["output_tokens"]
    totals["cacheReadTokens"] += row["cache_read_tokens"]
    totals["reasoningTokens"] += row["reasoning_tokens"]
    price = pricing.get(row["model_id"])
    if price is not None:
        cost = (row["input_tokens"] * price["input"] + row["output_tokens"] * price["output"]) / 1_000_000
        totals["cost"] = (totals["cost"] or 0) + cost


def _groups(
    rows: list[sqlite3.Row], key: str, label: str, pricing: Mapping[str, Mapping[str, float]]
) -> list[dict[str, Any]]:
    groups: dict[str, dict[str, Any]] = {}
    for row in rows:
        group = groups.setdefault(row[key], {"key": row[key], "label": row[label], **_totals()})
        _add(group, row, pricing)
    return sorted(groups.values(), key=lambda g: -g["requests"])


def _facets(rows: list[sqlite3.Row]) -> dict[str, Any]:
    keys: dict[str, str] = {}
    for row in rows:
        keys.setdefault(row["key_id"], row["key_name"])
    return {
        "keys": sorted(({"id": i, "name": n} for i, n in keys.items()), key=lambda k: k["name"]),
        "models": sorted({row["model_id"] for row in rows}),
        "protocols": sorted({row["protocol"] for row in rows}),
    }


def _detail(row: sqlite3.Row) -> dict[str, Any]:
    out = {field: row[column] for column, field in FIELDS.items() if column != "cache_write_tokens"}
    out["stream"] = row["stream"] == 1
    return out


class UsageStore:
    """SQLite ledger bound to one file."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._db: sqlite3.Connection | None = None

    def close(self) -> None:
        if self._db is not None:
            self._db.close()
            self._db = None

    def _open(self) -> sqlite3.Connection:
        if self._db is None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            db = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None)
            try:
                db.row_factory = sqlite3.Row
                db.execute("PRAGMA busy_timeout = 5000")
                db.execute("PRAGMA journal_mode = WAL")
                db.executescript(SCHEMA)
            except sqlite3.Error:
                db.close()
                raise
            self._db = db
        return self._db

    def record(self, entry: Mapping[str, Any]) -> None:
        """Insert one request (fields of :data:`FIELDS`) and drop rows past the retention."""
        db = self._open()
        db.execute(INSERT, [int(entry[f]) if f == "stream" else entry[f] for f in FIELDS.values()])
        db.execute("DELETE FROM requests WHERE time < ?", (entry["time"] - RETENTION_MS,))

    def summary(
        self,
        range_id: str,
        pricing: Mapping[str, Mapping[str, float]],
        row_filter: Mapping[str, str] | None = None,
        now: int | None = None,
    ) -> dict[str, Any]:
        row_filter = dict(row_filter or {})
        since = range_start(range_id, now)
        everything = (
            self._open().execute("SELECT * FROM requests WHERE time >= ? ORDER BY time DESC", (since,)).fetchall()
        )
        rows = [row for row in everything if _matches(row, row_filter)]
        totals = _totals()
        for row in rows:
            _add(totals, row, pricing)
        return {
            "range": range_id,
            "since": since,
            "filter": row_filter,
            "facets": _facets(everything),
            "totals": totals,
            "byModel": _groups(rows, "model_id", "model_id", pricing),
            "byKey": _groups(rows, "key_id", "key_name", pricing),
            "rows": [_detail(row) for row in rows[:DETAIL_LIMIT]],
            "matched": len(rows),
        }
