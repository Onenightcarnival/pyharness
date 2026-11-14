"""``ctx.subscriptions``: AI subscriptions as model routes and tools — Codex (OpenAI), ChatGPT, Google Antigravity
and Grok (xAI), signed in through their OAuth flows.

| member            | contract                                                                  |
|-------------------|---------------------------------------------------------------------------|
| ``providers``     | ``{id: Provider}``: login, accounts, catalog, usage, chat models, tools    |
| ``sync_routes()`` | publish the discovered models as ``ctx.llm`` routes ``codex`` / ``chatgpt`` / ``antigravity`` / |
|                   | ``grok``                                                                  |
| ``sync_tools()``  | register the provider tools that are switched on                          |

| config                 | meaning                                                        |
|------------------------|----------------------------------------------------------------|
| ``codexClientVersion`` | pin the Codex client version sent with catalog requests        |
| ``antigravity``        | ``clientId``, ``clientSecret``, ``baseURL``, ``userAgent``, ``projectId``, ``onboard``, |
|                        | ``maxTokens``                                                  |
|                        | ``userAgent`` replaces the Antigravity CLI signature, whose version is read once per start |
|                        | from the CLI auto-updater (a pinned version when the read fails) |
| ``models`` / ``chatgpt.models`` / ``grok.models`` | static catalogs (non-empty disables discovery for Codex / Grok) |
| ``stream_idle_timeout`` | seconds without data before a stream fails                   |

Sessions, preferences and catalogs live under ``<profile data>/toolkit/subscriptions/``. Routes under
``/api/subscriptions``: ``status``, ``login``, ``manual``, ``cancel``, ``logout``, ``default``, ``usage``,
``provider-settings`` (GET / PUT), ``model-default``, ``media/{name}``. Model routes are live only: they are rebuilt
from the stored sessions and the last-known catalogs at start and after every login / logout / discovery.
"""

from __future__ import annotations

from .service import Config, SubscriptionsService

__all__ = ["Config", "SubscriptionsService"]
