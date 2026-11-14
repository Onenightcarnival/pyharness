"""Shared by the ``web_search`` and ``web_fetch`` modules.

| name           | contract                                                        |
|----------------|-----------------------------------------------------------------|
| ``NOTICE``     | first line of every tool result: the content is untrusted data  |
| ``USER_AGENT`` | ``user-agent`` header of every outgoing request                 |
| ``Host``       | the service, as the two modules use it: config, API key, client |
| ``Pacer``      | at most ``limit`` request starts in any one-second window       |
"""

from __future__ import annotations

import asyncio
import time
from collections import deque
from typing import Protocol

import httpx

from pyharness import package_prompts

from .config import Config

PROMPTS = package_prompts(__file__)
NOTICE: str = PROMPTS["common"]["NOTICE"]
USER_AGENT = "pyharness/0.1 (+https://github.com/pyharness)"


class Pacer:
    """Sliding one-second window of request start times."""

    def __init__(self) -> None:
        self._starts: deque[float] = deque()

    async def wait(self, limit: int) -> None:
        """Return once fewer than ``limit`` requests started within the last second, and record this start."""
        while True:
            now = time.monotonic()
            while self._starts and self._starts[0] < now - 1.0:
                self._starts.popleft()
            if len(self._starts) < limit:
                self._starts.append(now)
                return
            await asyncio.sleep(self._starts[0] + 1.001 - now)


class Host(Protocol):
    """The service, as ``search`` and ``fetch`` use it."""

    config: Config
    pacer: Pacer

    def api_key(self) -> str | None: ...
    def client(self, timeout: float) -> httpx.AsyncClient: ...
