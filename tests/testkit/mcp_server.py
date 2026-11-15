"""A tiny stdio MCP server for tests: an `add` tool; with ``MCP_TEST_TOKEN`` set, a `token` tool that returns it."""

from __future__ import annotations

import os

from mcp.server.fastmcp import FastMCP

server = FastMCP("demo")


@server.tool()
def add(a: int, b: int) -> int:
    """Add two integers."""
    return a + b


if os.environ.get("MCP_TEST_TOKEN"):

    @server.tool()
    def token() -> str:
        """The value of ``MCP_TEST_TOKEN``."""
        return os.environ["MCP_TEST_TOKEN"]


if __name__ == "__main__":
    server.run()
