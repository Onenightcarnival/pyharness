"""Configuration models of the ``mcp`` entry."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


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
    connect_timeout: float = Field(
        20.0, description="Seconds to connect and list tools before a server counts as failed."
    )
