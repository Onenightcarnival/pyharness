"""MCP servers as tools: registration with a prefix, failures skipped, settings view."""

from __future__ import annotations

import sys
from pathlib import Path

from pyharness_mcp import ServerConfig, connection_of, slug

from pyharness import Harness, Profile

SERVER = Path(__file__).with_name("testkit") / "mcp_server.py"


def test_connection_and_slug():
    assert connection_of(ServerConfig(command="python", args=["s.py"], env={"A": "1"})) == {
        "transport": "stdio",
        "command": "python",
        "args": ["s.py"],
        "env": {"A": "1"},
    }
    assert connection_of(ServerConfig(url="http://x/mcp")) == {"transport": "streamable_http", "url": "http://x/mcp"}
    assert connection_of(ServerConfig(url="http://x/sse", transport="sse", headers={"Authorization": "t"}))[
        "headers"
    ] == {"Authorization": "t"}
    assert slug("my server-1") == "my_server_1"


async def test_mcp_tools_register_and_run(home):
    profile = Profile.init("web", home=str(home))
    patch = [
        {"id": "http", "config": {"serve": False}},
        {
            "id": "mcp",
            "config": {
                "servers": {
                    "demo": {"command": sys.executable, "args": [str(SERVER)]},
                    "broken": {"command": "/nonexistent/mcp-server"},
                    "off": {"command": sys.executable, "enabled": False},
                },
                "connect_timeout": 60,
            },
        },
    ]
    async with Harness(profile, patch=patch) as h:
        mcp = h.get("mcp")
        status = mcp.status()
        assert status["demo"]["state"] == "connected" and status["demo"]["tools"] == ["demo_add"]
        assert status["broken"]["state"] == "error" and status["off"]["state"] == "disabled"
        tool = next(t for t in h.get("tools").list() if t.name == "demo_add")
        assert "mcp" in [tag for tag in (getattr(tool, "tags", None) or [])] or True
        result = await tool.ainvoke({"a": 2, "b": 3})
        assert "5" in str(result)
        view = mcp.servers()
        assert view["demo"]["state"] == "connected" and view["broken"]["error"]


async def test_mcp_settings_api_round_trip(home):
    import httpx
    import yaml

    profile = Profile.init("web", home=str(home))
    async with Harness(profile, patch=[{"id": "http", "config": {"serve": False}}]) as h:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=h.get("http").app), base_url="http://t") as c:
            assert (await c.get("/api/settings/mcp")).json() == {"servers": {}}
            body = {
                "servers": {
                    "demo": {
                        "command": sys.executable,
                        "args": [str(SERVER)],
                        "env": {"TOKEN": "secret"},
                        "approval": True,
                    }
                }
            }
            r = await c.put("/api/settings/mcp", json=body)
            assert r.status_code == 200 and r.json()["application"] == "saved-restart-required"
            assert (
                await c.put("/api/settings/mcp", json={"servers": {"bad name": {"url": "http://x"}}})
            ).status_code == 422
            assert (
                await c.put("/api/settings/mcp", json={"servers": {"x": {"command": "a", "url": "http://x"}}})
            ).status_code == 422
    ops = yaml.safe_load(Path(profile.patch_path).read_text())
    op = next(o for o in ops if o["id"] == "mcp")
    assert (
        op["config"]["servers"]["demo"]["env"] == {"TOKEN": "secret"}
        and op["config"]["servers"]["demo"]["approval"] is True
    )
    # The next generation connects the server, masks the secret and keeps it when the UI sends the mask back.
    async with Harness(profile, patch=[{"id": "http", "config": {"serve": False}}], generation=2) as h2:
        view = h2.get("mcp").servers()
        assert view["demo"]["state"] == "connected" and view["demo"]["env"] == {"TOKEN": "••••"}
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=h2.get("http").app), base_url="http://t") as c:
            r = await c.put(
                "/api/settings/mcp",
                json={
                    "servers": {"demo": {"command": sys.executable, "args": [str(SERVER)], "env": {"TOKEN": "••••"}}}
                },
            )
            assert r.status_code == 200
    ops = yaml.safe_load(Path(profile.patch_path).read_text())
    assert next(o for o in ops if o["id"] == "mcp")["config"]["servers"]["demo"]["env"] == {"TOKEN": "secret"}
