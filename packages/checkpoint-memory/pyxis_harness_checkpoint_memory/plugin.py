from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.store.memory import InMemoryStore
from pydantic import BaseModel

name = "pyxis-harness-checkpoint-memory"
doc = "Persistence provider in process memory, for temporary sessions: ``ctx.temporary``."
inject: list[str] = []


class Config(BaseModel):
    pass


@dataclass(frozen=True)
class Temporary:
    """Persistence of temporary sessions: the pair a durable provider gives as ``checkpointer`` and ``store``."""

    checkpointer: Any
    store: Any


def apply(ctx: Any, config: Config) -> None:
    ctx.provide("temporary", Temporary(InMemorySaver(), InMemoryStore()))
