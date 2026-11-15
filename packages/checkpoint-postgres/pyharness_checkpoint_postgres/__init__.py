"""
Persistence provider on PostgreSQL: ``ctx.checkpointer`` and ``ctx.store``.

| service              | implementation         |
|----------------------|------------------------|
| ``ctx.checkpointer`` | ``AsyncPostgresSaver`` |
| ``ctx.store``        | ``AsyncPostgresStore`` |

- One async connection pool: autocommit, dict rows, ``prepare_threshold=0``.
- The database encoding is UTF8; ``SQL_ASCII`` fails the plugin.
"""

from __future__ import annotations

from typing import Any

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.store.postgres.aio import AsyncPostgresStore
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool
from pydantic import BaseModel, Field

name = "pyharness-checkpoint-postgres"
inject: list[str] = []


class Config(BaseModel):
    dsn: str = Field(..., description="libpq connection string: postgresql://user:pass@host:5432/db")
    pool_min: int = 1
    pool_max: int = 10


async def apply(ctx: Any, config: Config) -> None:
    pool = AsyncConnectionPool(
        conninfo=config.dsn,
        min_size=config.pool_min,
        max_size=config.pool_max,
        open=False,
        kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row},
    )
    await pool.open(wait=True, timeout=15)
    ctx.on_dispose(pool.close)
    async with pool.connection() as conn:
        row = await (await conn.execute("SHOW server_encoding")).fetchone()
    encoding = (row or {}).get("server_encoding")
    if encoding == "SQL_ASCII":
        raise RuntimeError(
            "database encoding is SQL_ASCII; required: UTF8 (CREATE DATABASE ... ENCODING 'UTF8' TEMPLATE template0)"
        )
    saver = AsyncPostgresSaver(pool)
    await saver.setup()
    store = AsyncPostgresStore(pool)
    await store.setup()
    ctx.provide("checkpointer", saver)
    ctx.provide("store", store)


__all__ = ["Config", "apply", "name"]
