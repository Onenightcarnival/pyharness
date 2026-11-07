"""A tiny stdio MCP server for tests: one `add` tool."""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

server = FastMCP("demo")


@server.tool()
def add(a: int, b: int) -> int:
    """Add two integers."""
    return a + b


if __name__ == "__main__":
    server.run()
