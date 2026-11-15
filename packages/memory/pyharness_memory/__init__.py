"""
``ctx.memory``: the agent's layered career memory (profile → work → project → lesson) with version history.

| member                    | contract                                                                 |
|---------------------------|--------------------------------------------------------------------------|
| ``store``                 | :class:`MemoryStore`: ``state()``, ``commit()``, ``clear()``, ``diff()`` |
| ``sync()``                | register the tools and prompt section while agent access is on          |

| config         | meaning                                                               |
|----------------|-----------------------------------------------------------------------|
| ``path``       | SQLite file (default ``<profile data>/toolkit/memory.sqlite``)        |
| ``busy_timeout`` | seconds to wait for a locked database                               |

Tools ``memory_get`` and ``memory_save`` (shapes and prompt as dsh-memory, so prompts written for either work) exist
only while the Memory page's "Allow agent access" switch is on. No model is called: memory is written by the agent
during its own turns and by the user on the page. Routes under ``/api/memory``: ``GET`` (state), ``GET ?diff=N``,
``POST`` (commit), ``PATCH`` (agent access), ``DELETE`` (clear).
"""

from __future__ import annotations

from .service import GUIDANCE, Config, MemoryService
from .store import MemoryStore, MemoryStoreError, sort_entries

__all__ = ["GUIDANCE", "Config", "MemoryService", "MemoryStore", "MemoryStoreError", "sort_entries"]
