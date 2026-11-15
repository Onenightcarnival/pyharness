"""MCP servers as tools: registration with a prefix, failures skipped, credential templates, settings view."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import httpx
import yaml

from pyharness import Harness, Profile
from pyharness_mcp import MASK, Config, MCPService, ServerConfig, connection_of, expand, redact, references, slug

SERVER = Path(__file__).with_name("testkit") / "mcp_server.py"
HTTP_OFF = {"id": "http", "config": {"serve": False}}


class NoProfile:
    """A context without services."""

    def get(self, key: str, default: Any = None) -> Any:
        return default


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


def test_credential_templates():
    stdio = ServerConfig(
        command="bin-${credential:PYH_T_BIN}",
        args=["--key", "${credential:PYH_T_KEY}", "--pair=${credential:PYH_T_KEY}:${credential:PYH_T_OTHER}"],
        env={"TOKEN": "${credential:PYH_T_TOKEN}", "PLAIN": "x"},
        cwd="/w/${credential:PYH_T_KEY}",
    )
    http = ServerConfig(
        url="https://x/mcp?key=${credential:PYH_T_KEY}",
        headers={"Authorization": "Bearer ${credential:PYH_T_TOKEN}", "X-Plain": "p"},
    )
    assert references(stdio) == ["PYH_T_BIN", "PYH_T_KEY", "PYH_T_OTHER", "PYH_T_TOKEN"]
    assert references(http) == ["PYH_T_KEY", "PYH_T_TOKEN"] and references(ServerConfig(command="x")) == []
    values = {"PYH_T_BIN": "b1", "PYH_T_KEY": "k-123", "PYH_T_TOKEN": "tok/456", "PYH_T_OTHER": ""}
    expanded, resolved, missing = expand(stdio, values.get)
    assert expanded.command == "bin-b1"
    assert expanded.args == ["--key", "k-123", "--pair=k-123:${credential:PYH_T_OTHER}"]
    assert expanded.env == {"TOKEN": "tok/456", "PLAIN": "x"} and expanded.cwd == "/w/k-123"
    assert resolved == ["b1", "k-123", "tok/456"] and missing == ["PYH_T_OTHER"]
    assert stdio.env["TOKEN"] == "${credential:PYH_T_TOKEN}"
    expanded, resolved, missing = expand(http, values.get)
    assert expanded.url == "https://x/mcp?key=k-123" and missing == []
    assert expanded.headers == {"Authorization": "Bearer tok/456", "X-Plain": "p"}
    # Text outside the reference rule is literal.
    odd = ServerConfig(command="x", args=["${credential:lower}", "${credential:}", "$credential:PYH_T_KEY"])
    assert references(odd) == [] and expand(odd, values.get) == (odd, [], [])
    # Values of three characters or more and their URL-encoded form are redacted, the longest first.
    text = "GET https://x/mcp?key=k-123 answered 401 for tok/456 and tok%2F456, b1"
    assert redact(text, resolved) == "GET https://x/mcp?key=[redacted] answered 401 for [redacted] and [redacted], b1"
    assert redact("abcdef abc", ["abc", "abcdef"]) == "[redacted] [redacted]"
    assert redact("nothing", []) == "nothing"


async def test_credentials_at_start_and_probe(home, monkeypatch, caplog):
    for name in ("PYH_T_MCP_TOKEN", "PYH_T_MCP_ABSENT"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("PYH_T_MCP_ENV", "from-env")
    profile = Profile.init("web", home=str(home))
    profile.credentials.set("PYH_T_MCP_TOKEN", "s3cr3t-token")
    demo = {"command": sys.executable, "args": [str(SERVER)]}
    servers = {
        "stored": {**demo, "env": {"MCP_TEST_TOKEN": "tok:${credential:PYH_T_MCP_TOKEN}", "PLAIN": "plain"}},
        "waiting": {**demo, "env": {"MCP_TEST_TOKEN": "${credential:PYH_T_MCP_ABSENT}"}},
        "broken": {"command": "/nonexistent/${credential:PYH_T_MCP_TOKEN}"},
        "remote": {
            "url": "http://127.0.0.1:9/mcp",
            "headers": {"Authorization": "Bearer ${credential:PYH_T_MCP_ENV}", "X-Plain": "p"},
            "enabled": False,
        },
    }
    patch = [HTTP_OFF, {"id": "mcp", "config": {"servers": servers, "connect_timeout": 60}}]
    async with Harness(profile, patch=patch) as h:
        mcp = h.get("mcp")
        status = mcp.status()
        # The stored value reaches the server process; the template stays in the configuration.
        assert status["stored"] == {"state": "connected", "tools": ["stored_add", "stored_token"]}
        tool = next(t for t in h.get("tools").list() if t.name == "stored_token")
        assert "tok:s3cr3t-token" in str(await tool.ainvoke({}))
        assert status["waiting"] == {"state": "waiting-credentials", "missing": ["PYH_T_MCP_ABSENT"], "tools": []}
        assert status["broken"]["state"] == "error" and "/nonexistent/[redacted]" in status["broken"]["error"]
        assert "PYH_T_MCP_ABSENT" in caplog.text and "s3cr3t-token" not in caplog.text
        # The view shows a template as written, masks any other value, and describes each reference.
        view = mcp.servers()
        assert view["stored"]["env"] == {"MCP_TEST_TOKEN": "tok:${credential:PYH_T_MCP_TOKEN}", "PLAIN": MASK}
        assert view["stored"]["credentials"] == [
            {"reference": "PYH_T_MCP_TOKEN", "configured": True, "source": "store"}
        ]
        assert view["waiting"]["missing"] == ["PYH_T_MCP_ABSENT"] and view["waiting"]["credentials"] == [
            {"reference": "PYH_T_MCP_ABSENT", "configured": False, "source": None}
        ]
        assert view["remote"]["headers"] == {"Authorization": "Bearer ${credential:PYH_T_MCP_ENV}", "X-Plain": MASK}
        assert view["remote"]["credentials"] == [{"reference": "PYH_T_MCP_ENV", "configured": True, "source": "env"}]
        assert view["broken"]["credentials"][0]["configured"] is True and "s3cr3t-token" not in str(view)
        # A probe resolves the same way: environment first, then the store.
        probe = ServerConfig(**demo, env={"MCP_TEST_TOKEN": "${credential:PYH_T_MCP_ENV}"})
        assert await mcp.probe(probe) == {"ok": True, "tools": ["add", "token"]}
        probe = ServerConfig(
            command=sys.executable,
            args=[str(SERVER), "${credential:PYH_T_MCP_ABSENT}"],
            headers={"X": "${credential:PYH_T_MCP_NONE}"},
        )
        assert await mcp.probe(probe) == {
            "ok": False,
            "code": "waiting-credentials",
            "error": "missing credentials: PYH_T_MCP_ABSENT, PYH_T_MCP_NONE",
        }
        result = await mcp.probe(ServerConfig(command="/nonexistent/${credential:PYH_T_MCP_TOKEN}"))
        assert result["code"] == "error" and "/nonexistent/[redacted]" in result["error"]


async def test_credentials_without_profile(monkeypatch):
    monkeypatch.delenv("PYH_T_MCP_ENV", raising=False)
    cfg = ServerConfig(
        command=sys.executable, args=[str(SERVER)], env={"MCP_TEST_TOKEN": "${credential:PYH_T_MCP_ENV}"}
    )
    mcp = MCPService(NoProfile(), Config(servers={"demo": cfg}, connect_timeout=60))
    assert (await mcp.probe(cfg))["code"] == "waiting-credentials"
    assert mcp.servers()["demo"]["credentials"] == [{"reference": "PYH_T_MCP_ENV", "configured": False, "source": None}]
    monkeypatch.setenv("PYH_T_MCP_ENV", "from-env")
    assert await mcp.probe(cfg) == {"ok": True, "tools": ["add", "token"]}
    assert mcp.servers()["demo"]["credentials"] == [{"reference": "PYH_T_MCP_ENV", "configured": True, "source": "env"}]


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
        assert "mcp" in list(getattr(tool, "tags", None) or []) or True
        result = await tool.ainvoke({"a": 2, "b": 3})
        assert "5" in str(result)
        view = mcp.servers()
        assert view["demo"]["state"] == "connected" and view["broken"]["error"]


async def test_mcp_settings_api_round_trip(home, monkeypatch):
    monkeypatch.delenv("PYH_T_MCP_TOKEN", raising=False)
    profile = Profile.init("web", home=str(home))
    template = "${credential:PYH_T_MCP_TOKEN}"
    async with (
        Harness(profile, patch=[{"id": "http", "config": {"serve": False}}]) as h,
        httpx.AsyncClient(transport=httpx.ASGITransport(app=h.get("http").app), base_url="http://t") as c,
    ):
        assert (await c.get("/api/settings/mcp")).json() == {"servers": {}}
        body = {
            "servers": {
                "demo": {
                    "command": sys.executable,
                    "args": [str(SERVER)],
                    "env": {"TOKEN": "secret", "MCP_TEST_TOKEN": template},
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

    ops = yaml.safe_load(Path(profile.patch_path).read_text(encoding="utf-8"))
    op = next(o for o in ops if o["id"] == "mcp")
    assert (
        op["config"]["servers"]["demo"]["env"] == {"TOKEN": "secret", "MCP_TEST_TOKEN": template}
        and op["config"]["servers"]["demo"]["approval"] is True
    )
    profile.credentials.set("PYH_T_MCP_TOKEN", "s3cr3t-token")
    # The next generation connects the server with the stored credential, masks the plain secret, shows the template
    # as written, and keeps both when the UI sends the view back.
    async with Harness(profile, patch=[{"id": "http", "config": {"serve": False}}], generation=2) as h2:
        view = h2.get("mcp").servers()
        assert view["demo"]["state"] == "connected" and view["demo"]["tools"] == ["demo_add", "demo_token"]
        assert view["demo"]["env"] == {"TOKEN": "••••", "MCP_TEST_TOKEN": template}
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=h2.get("http").app), base_url="http://t") as c:
            shown = (await c.get("/api/settings/mcp")).json()["servers"]["demo"]
            assert shown["env"] == view["demo"]["env"] and "s3cr3t-token" not in str(shown)
            r = await c.put(
                "/api/settings/mcp",
                json={"servers": {"demo": {"command": sys.executable, "args": [str(SERVER)], "env": shown["env"]}}},
            )
            assert r.status_code == 200
    ops = yaml.safe_load(Path(profile.patch_path).read_text(encoding="utf-8"))
    assert next(o for o in ops if o["id"] == "mcp")["config"]["servers"]["demo"]["env"] == {
        "TOKEN": "secret",
        "MCP_TEST_TOKEN": template,
    }
    assert "s3cr3t-token" not in Path(profile.patch_path).read_text(encoding="utf-8")
