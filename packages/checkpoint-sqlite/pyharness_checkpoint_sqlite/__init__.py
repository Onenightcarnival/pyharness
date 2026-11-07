"""Persistence provider on SQLite: ``ctx.checkpointer`` and ``ctx.store``.

| service              | implementation       | file                  |
|----------------------|----------------------|-----------------------|
| ``ctx.checkpointer`` | ``AsyncSqliteSaver`` | ``config.path``       |
| ``ctx.store``        | ``AsyncSqliteStore`` | ``config.store_path`` |

Same entry id, PostgreSQL provider::

    - id: checkpoint
      name: pyharness-checkpoint-postgres
      config: {dsn: "${env:PYH_POSTGRES_DSN}"}
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

name = "pyharness-checkpoint-sqlite"
inject: list[str] = []


class Config(BaseModel):
    path: str = Field("${data_dir}/checkpoints.sqlite", description="LangGraph checkpoints.")
    store_path: str = Field("${data_dir}/store.sqlite", description="LangGraph store: session metadata, agent memory.")


async def apply(ctx: Any, config: Config) -> None:
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
    from langgraph.store.sqlite.aio import AsyncSqliteStore

    for raw in (config.path, config.store_path):
        Path(raw).expanduser().parent.mkdir(parents=True, exist_ok=True)
    saver = await ctx.enter(AsyncSqliteSaver.from_conn_string(str(Path(config.path).expanduser())))
    await saver.setup()
    store = await ctx.enter(AsyncSqliteStore.from_conn_string(str(Path(config.store_path).expanduser())))
    await store.setup()
    ctx.provide("checkpointer", saver)
    ctx.provide("store", store)
    ctx.logger.debug("sqlite persistence at %s / %s", config.path, config.store_path)


__all__ = ["Config", "apply", "name"]
