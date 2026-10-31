"""``ctx.mcp``: tools of MCP servers, registered into ``ctx.tools`` at boot.

| config                 | meaning                                                                          |
|------------------------|----------------------------------------------------------------------------------|
| ``servers.<name>``     | one server: ``command`` + ``args`` (+ ``env``, ``cwd``) for stdio, or ``url`` (+ ``headers``) for ``streamable_http`` / ``sse`` |
| ``servers.<name>.enabled`` | ``false`` keeps the server configured but unconnected                         |
| ``servers.<name>.approval`` | approval gate for every tool of the server (``true`` or a LangChain ``InterruptOnConfig``) |
| ``servers.<name>.prefix`` | tool names become ``<server>_<tool>`` (default) to keep servers apart        |
| ``connect_timeout``    | seconds to list a server's tools before it is marked ``error``                   |

A server that fails to connect is reported in :meth:`MCPService.status` and skipped; the harness boots without it.
Tools run through the ``tools/execute`` pipeline like any registered tool, so permission modes and approvals apply.
Secrets in ``env`` and ``headers`` come from the profile configuration (``${env:VAR}`` interpolation keeps them out of files).
"""

from __future__ import annotations

import asyncio
import re
from typing import Any, Literal

from pydantic import BaseModel, Field

from pyharness import Service


class ServerConfig(BaseModel):
    transport: Literal["stdio", "streamable_http", "sse"] | None = Field(
        None, description="Defaults to stdio with `command`, else streamable_http."
    )
    command: str | None = Field(None, description="Executable of a stdio server.")
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)
    cwd: str | None = None
    url: str | None = Field(None, description="Endpoint of an HTTP (streamable_http) or SSE server.")
    headers: dict[str, str] = Field(default_factory=dict)
    enabled: bool = True
    approval: bool | dict[str, Any] = Field(False, description="Approval gate for the server's tools.")
    prefix: bool = Field(True, description="Prefix tool names with the server name.")


class Config(BaseModel):
    servers: dict[str, ServerConfig] = Field(default_factory=dict)
    connect_timeout: float = Field(20.0, description="Seconds to connect and list tools before a server counts as failed.")


def slug(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_]+", "_", name).strip("_") or "server"


def connection_of(cfg: ServerConfig) -> dict[str, Any]:
    """The ``langchain-mcp-adapters`` connection for a server configuration."""
    if cfg.command:
        conn: dict[str, Any] = {"transport": "stdio", "command": cfg.command, "args": list(cfg.args)}
        if cfg.env:
            conn["env"] = dict(cfg.env)
        if cfg.cwd:
            conn["cwd"] = cfg.cwd
        return conn
    if not cfg.url:
        raise ValueError("a server needs `command` (stdio) or `url` (streamable_http / sse)")
    conn = {"transport": cfg.transport or "streamable_http", "url": cfg.url}
    if cfg.headers:
        conn["headers"] = dict(cfg.headers)
    return conn


MASK = "••••"


class MCPService(Service):
    """MCP servers as tools."""

    key = "mcp"
    name = "pyharness-mcp"
    inject = ["tools"]
    Config = Config

    def __init__(self, ctx: Any, config: Config) -> None:
        super().__init__(ctx, config)
        self._status: dict[str, dict[str, Any]] = {}

    async def start(self) -> None:
        for name, cfg in self.config.servers.items():
            if not cfg.enabled:
                self._status[name] = {"state": "disabled", "tools": []}
                continue
            try:
                tools = await asyncio.wait_for(self._load(name, cfg), self.config.connect_timeout)
            except Exception as exc:  # noqa: BLE001 - one server must not stop the boot
                self._status[name] = {"state": "error", "error": f"{type(exc).__name__}: {exc}"[:500], "tools": []}
                self.ctx.logger.warning("mcp server %s unavailable: %s", name, exc)
                continue
            registered: list[str] = []
            for tool in tools:
                if cfg.prefix:
                    tool.name = f"{slug(name)}_{tool.name}"
                try:
                    self.ctx.tools.register(tool, approval=cfg.approval, tags=("mcp", name))
                    registered.append(tool.name)
                except Exception as exc:  # noqa: BLE001 - name clash with another plugin's tool
                    self.ctx.logger.warning("mcp tool %s of %s not registered: %s", tool.name, name, exc)
            self._status[name] = {"state": "connected", "tools": registered}

    async def _load(self, name: str, cfg: ServerConfig) -> list[Any]:
        from langchain_mcp_adapters.client import MultiServerMCPClient

        client = MultiServerMCPClient({name: connection_of(cfg)})
        return list(await client.get_tools())

    # ------------------------------------------------------------------ views
    def status(self) -> dict[str, dict[str, Any]]:
        """Per server: ``state`` (connected / error / disabled), ``tools`` (registered names), ``error``."""
        return {name: dict(value) for name, value in self._status.items()}

    def servers(self) -> dict[str, dict[str, Any]]:
        """Configured servers with ``env`` and ``headers`` values masked, plus their status."""
        out = {}
        for name, cfg in self.config.servers.items():
            data = cfg.model_dump()
            data["env"] = {k: MASK for k in cfg.env}
            data["headers"] = {k: MASK for k in cfg.headers}
            out[name] = {**data, **self._status.get(name, {"state": "disabled" if not cfg.enabled else "unknown", "tools": []})}
        return out


__all__ = ["Config", "MCPService", "ServerConfig", "connection_of", "slug"]
