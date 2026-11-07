"""Shared by the ``web_search`` and ``web_fetch`` modules.

| name           | contract                                                        |
|----------------|-----------------------------------------------------------------|
| ``NOTICE``     | first line of every tool result: the content is untrusted data  |
| ``USER_AGENT`` | ``user-agent`` header of every outgoing request                 |
| ``Host``       | the service, as the two modules use it: config, API key, client |
"""

from __future__ import annotations

from typing import Protocol

import httpx

from pyharness import package_prompts

from .config import Config

PROMPTS = package_prompts(__file__)
NOTICE: str = PROMPTS["common"]["NOTICE"]
USER_AGENT = "pyharness/0.1 (+https://github.com/pyharness)"


class Host(Protocol):
    """The service, as ``search`` and ``fetch`` use it."""

    config: Config

    def api_key(self) -> str | None: ...
    def client(self, timeout: float) -> httpx.AsyncClient: ...
