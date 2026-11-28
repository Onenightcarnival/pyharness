"""Web tools: HTML to text, web_fetch and web_search over a mocked transport, settings, the agent switch."""

from __future__ import annotations

import json
import time
from textwrap import dedent

import httpx
import pytest
import yaml

from pyxis_harness import Harness, Profile
from pyxis_harness_web_tools import format_search, html_to_text, map_search_response, parse_search_response
from pyxis_harness_web_tools.common import Pacer

HTTP_OFF = {"id": "http", "config": {"serve": False}}
TOOLS_OFF = {"id": "web-tools", "merge": True, "config": {"agent_tools": False}}
SETTINGS = "/api/web-tools/settings"
WEB = {"web_search", "web_fetch"}
PAGE = dedent(
    """
    <html><head><title>Hello &amp; welcome</title><style>p{}</style><script>alert(1)</script></head>
    <body><nav><a href="/about">About</a></nav><h1>Heading</h1><p>First   paragraph with <a href="https://x.test/doc">a link</a>.</p>
    <ul><li>one</li><li>two</li></ul><pre>  code
      block</pre><img alt="diagram"></body></html>
    """  # noqa: E501
).strip()

API_RESPONSE = {
    "results": [
        {
            "url": "https://a.test/1",
            "title": "Result A",
            "snippet": "short",
            "summary": "A long   summary of the page\nwith details",
            "date": "2026-10-01",
        },
        {"url": "https://b.test/2", "title": "", "snippet": "", "date": None},
    ]
}

SEARCH_RESPONSE = {
    "content": [
        {"type": "server_tool_use", "name": "web_search", "input": {"query": "pyxis_harness"}},
        {
            "type": "web_search_tool_result",
            "content": [
                {"type": "web_search_result", "url": "https://a.test/1", "title": "Result A", "page_age": "2026-10-01"},
                {"type": "web_search_result", "url": "https://b.test/2", "title": "Result B"},
                {"type": "web_search_result", "url": "https://a.test/1", "title": "dup"},
            ],
        },
        {"type": "text", "text": "A says hi.", "citations": [{"url": "https://a.test/1", "cited_text": "hi from A"}]},
        {"type": "text", "text": " B too."},
    ]
}


def client(h):
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=h.get("http").app), base_url="http://t", timeout=120)


def registered(h):
    """The web tools in the registry."""
    return WEB & {t.name for t in h.get("tools").list()}


def tools_of(graph):
    """Names of the tools a compiled agent graph can call."""
    node = getattr(graph, "bound", graph).nodes.get("tools")
    return set(node.bound.tools_by_name) if node is not None else set()


def stored(profile):
    """The ``web-tools`` config of the profile patch."""
    ops = {o["id"]: o["config"] for o in yaml.safe_load((profile.dir / "harness.patch.yaml").read_text())}
    return ops.get("web-tools")


def test_html_to_text_and_search_parsing():
    title, text = html_to_text(PAGE, "https://x.test/page")
    assert title == "Hello & welcome"
    assert "alert" not in text and "p{}" not in text
    assert "[About](https://x.test/about)" in text and "# Heading" in text
    assert "First paragraph with [a link](https://x.test/doc)." in text
    assert "- one\n- two" in text and "```\n  code\n  block\n```" in text and "[image: diagram]" in text
    answer, sources = parse_search_response(SEARCH_RESPONSE)
    assert answer == "A says hi. B too."
    assert sources == [
        {"url": "https://a.test/1", "title": "Result A", "snippet": "hi from A", "published_at": "2026-10-01"},
        {"url": "https://b.test/2", "title": "Result B"},
    ]
    out = format_search(answer, sources, False)
    assert out.startswith("External web content") and "- [Result A](https://a.test/1) — hi from A (2026-10-01)" in out
    # Search API: sources in provider order; the summary is collapsed and capped, and wins over the snippet.
    mapped = map_search_response(API_RESPONSE, 20)
    assert mapped == [
        {
            "url": "https://a.test/1",
            "title": "Result A",
            "snippet": "short",
            "published_at": "2026-10-01",
            "summary": "A long summary of t…",
        },
        {"url": "https://b.test/2"},
    ]
    listed = format_search("", mapped, False)
    assert (
        "- [Result A](https://a.test/1) — A long summary of t… (2026-10-01)" in listed
        and "- [b.test](https://b.test/2)" in listed
    )
    assert "No results found." in format_search("", [], False)
    for body in ({}, {"results": "x"}, {"results": [{"title": "no url"}]}, []):
        with pytest.raises(ValueError):
            map_search_response(body, 800)


async def test_pacer():
    pacer = Pacer()
    started = time.monotonic()
    for _ in range(3):
        await pacer.wait(3)
    assert time.monotonic() - started < 0.5
    await pacer.wait(3)  # the fourth start waits for the window to move
    assert time.monotonic() - started >= 1.0


async def test_tools_over_mock_transport(home, monkeypatch):
    profile = Profile.init("web", home=str(home))
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.path == "/v1/tools/search":
            assert request.headers["authorization"] == "Bearer sk-test" and "x-api-key" not in request.headers
            assert json.loads(request.content) == {"query": "pyxis_harness", "count": 10, "need_content": False}
            if request.url.host == "moved.test":
                return httpx.Response(302, headers={"location": "https://elsewhere.test/"})
            if request.url.host == "busy.test":
                return httpx.Response(429, json={"error": {"message": "slow down"}})
            return httpx.Response(200, json=API_RESPONSE)
        if request.url.path.endswith("/messages"):
            assert request.headers["x-api-key"] == "sk-test" and request.headers["anthropic-version"] == "2023-06-01"
            body = json.loads(request.content)
            assert (
                body["tools"][0]["type"] == "web_search_20250305"
                and "pyxis_harness" in body["messages"][0]["content"][0]["text"]
            )
            return httpx.Response(200, json=SEARCH_RESPONSE)
        if request.url.path == "/page":
            return httpx.Response(200, headers={"content-type": "text/html; charset=utf-8"}, text=PAGE)
        if request.url.path == "/data.json":
            return httpx.Response(200, headers={"content-type": "application/json"}, json={"a": [1, 2]})
        if request.url.path == "/bin":
            return httpx.Response(200, headers={"content-type": "application/octet-stream"}, content=b"\x00\x01")
        return httpx.Response(404, text="nope")

    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    async with Harness(profile, patch=[HTTP_OFF]) as h:
        web = h.get("web")
        web.transport = httpx.MockTransport(handler)
        tools = {t.name: t for t in h.get("tools").list()}
        assert {"web_search", "web_fetch"} <= set(tools)
        # No key: the tool answers with instructions instead of failing the turn.
        missing = await tools["web_search"].ainvoke({"query": "pyxis_harness"})
        assert missing.startswith("Error:") and "DEEPSEEK_API_KEY" in missing
        assert web.status()["search"]["configured"] is False
        profile.credentials.set("DEEPSEEK_API_KEY", "sk-test")
        # Default provider: one direct Search API request; the sources carry their summaries.
        out = await tools["web_search"].ainvoke({"query": "pyxis_harness"})
        assert "- [Result A](https://a.test/1) — A long summary of the page with details (2026-10-01)" in out
        assert "- [b.test](https://b.test/2)" in out and "Cite the relevant URLs" in out
        assert seen[-1].url == "https://api.deepseek.com/v1/tools/search"
        status = web.status()["search"]
        assert status["configured"] is True and status["source"] == "store"
        assert status["provider"] == "deepseek-search-api" and status["base_url"] == "https://api.deepseek.com/v1/tools"
        # A redirect and a rate limit fail the search with the endpoint named.
        web.config.search_base_url = "https://moved.test/v1/tools"
        moved = await tools["web_search"].ainvoke({"query": "pyxis_harness"})
        assert moved.startswith("Error: DeepSeek API error (HTTP 302)") and "moved.test" in moved
        web.config.search_base_url = "https://busy.test/v1/tools/"
        assert "HTTP 429): slow down" in await tools["web_search"].ainvoke({"query": "pyxis_harness"})
        # The legacy provider: a Messages call with the web_search server tool, an answer with cited sources.
        web.config.search_provider = "deepseek-legacy"
        out = await tools["web_search"].ainvoke({"query": "pyxis_harness"})
        assert (
            "A says hi. B too." in out
            and "[Result A](https://a.test/1)" in out
            and "[Result B](https://b.test/2)" in out
        )
        assert web.status()["search"]["provider"] == "deepseek-legacy" and web.status()["search"]["model"]
        page = await tools["web_fetch"].ainvoke({"url": "https://x.test/page"})
        assert "Title: Hello & welcome" in page and "# Heading" in page and "[a link](https://x.test/doc)" in page
        data = await tools["web_fetch"].ainvoke({"url": "https://x.test/data.json"})
        assert '"a": [\n    1,\n    2\n  ]' in data
        assert "binary content" in await tools["web_fetch"].ainvoke({"url": "https://x.test/bin"})
        assert "Status: 404" in await tools["web_fetch"].ainvoke({"url": "https://x.test/missing"})
        assert (await tools["web_fetch"].ainvoke({"url": "ftp://x.test/f"})).startswith("Error:")
        small = await tools["web_fetch"].ainvoke({"url": "https://x.test/page", "max_chars": 40})
        assert "truncated" in small


async def test_web_tools_settings(home, monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    profile = Profile.init("web", home=str(home))
    async with (
        Harness(profile, patch=[HTTP_OFF]) as h,
        httpx.AsyncClient(transport=httpx.ASGITransport(app=h.get("http").app), base_url="http://t") as c,
    ):
        web, lifecycle = h.get("web"), h.ctx.lifecycle
        current = (await c.get("/api/web-tools/settings")).json()
        assert (current["search"], current["fetch"], current["search_provider"]) == (True, True, "deepseek-search-api")
        assert current["key"] == {"reference": "DEEPSEEK_API_KEY", "configured": False, "source": None}
        # Provider and counts apply at once.
        saved = (
            await c.put("/api/web-tools/settings", json={"search_provider": "deepseek-legacy", "max_results": 3})
        ).json()
        assert (saved["application"], saved["search_provider"], saved["max_results"]) == (
            "applied",
            "deepseek-legacy",
            3,
        )
        assert web.config.max_results == 3 and lifecycle.restart_pending is None
        refused = await c.put("/api/web-tools/settings", json={"max_results": 500})
        assert refused.status_code == 422 and refused.json()["detail"].startswith("max_results: ")
        assert (await c.put("/api/web-tools/settings", json={"search_provider": "elsewhere"})).status_code == 422
        # The key goes to the profile's credential file and is never returned.
        keyed = (await c.put("/api/web-tools/settings", json={"api_key": " sk-test "})).json()
        assert keyed["key"] == {"reference": "DEEPSEEK_API_KEY", "configured": True, "source": "store"}
        assert "sk-test" not in json.dumps(keyed) and web.api_key() == "sk-test"
        assert (await c.put("/api/web-tools/settings", json={"api_key": ""})).json()["key"]["configured"] is False
        assert web.api_key() is None
        # Which tools the agent has changes with the next generation.
        off = (await c.put("/api/web-tools/settings", json={"fetch": False})).json()
        assert off["application"] == "restart" and lifecycle.restart_pending["reasons"] == ["web tools settings"]
        saved = {o["id"]: o["config"] for o in yaml.safe_load((profile.dir / "harness.patch.yaml").read_text())}
        assert saved["web-tools"] == {"search_provider": "deepseek-legacy", "max_results": 3, "fetch": False}


async def test_agent_tools_switch(home, workspace):
    profile = Profile.init("web", home=str(home))
    async with Harness(profile, patch=[HTTP_OFF]) as h, client(h) as c:
        web, agents = h.get("web"), h.get("agents")
        chat = (await c.post("/api/sessions", json={"temporary": True})).json()
        session = (await c.post("/api/sessions", json={})).json()

        async def in_graphs():
            """The tools of the temporary chat and of the session, as their next turn has them."""
            return tools_of(await agents.graph_for(chat)), tools_of(await agents.graph_for(session))

        # Default: on.
        assert (await c.get(SETTINGS)).json()["agent_tools"] is True and registered(h) == WEB
        in_chat, in_session = await in_graphs()
        assert in_chat == WEB and in_session > WEB
        assert (web.status()["search"]["enabled"], web.status()["fetch"]["enabled"]) == (True, True)
        # Off at run time: unregistered at once, absent from the temporary chat and the session, no restart.
        off = (await c.put(SETTINGS, json={"agent_tools": False})).json()
        assert (off["application"], off["agent_tools"]) == ("applied", False)
        assert registered(h) == set() and h.ctx.lifecycle.restart_pending is None
        in_chat, in_session = await in_graphs()
        assert in_chat == set() and not in_session & WEB and "write_file" in in_session
        assert (web.status()["search"]["enabled"], web.status()["fetch"]["enabled"]) == (False, False)
        # On again.
        on = (await c.put(SETTINGS, json={"agent_tools": True})).json()
        assert (on["application"], on["agent_tools"]) == ("applied", True) and registered(h) == WEB
        in_chat, in_session = await in_graphs()
        assert in_chat == WEB and in_session > WEB and h.ctx.lifecycle.restart_pending is None
        await c.put(SETTINGS, json={"agent_tools": False})
    # The stored choice outlives the restart.
    assert stored(profile) == {"agent_tools": False}
    async with Harness(profile, patch=[HTTP_OFF]) as h, client(h) as c:
        assert registered(h) == set() and (await c.get(SETTINGS)).json()["agent_tools"] is False


async def test_agent_tools_default_and_stored_choice(home):
    profile = Profile.init("web", home=str(home))
    # The config default, off through a patch.
    async with Harness(profile, patch=[HTTP_OFF, TOOLS_OFF]) as h:
        assert registered(h) == set() and h.get("web").settings()["agent_tools"] is False
    # A manifest of the four-bundle list with ``web`` disabled: the same default.
    profile.save_manifest({**profile.manifest(), "disabled": ["web"]})
    async with Harness(profile, patch=[HTTP_OFF]) as h, client(h) as c:
        assert registered(h) == set() and (await c.get(SETTINGS)).json()["agent_tools"] is False
        assert (await c.put(SETTINGS, json={"agent_tools": True})).json()["agent_tools"] is True
        assert registered(h) == WEB
    # The stored choice wins over that default.
    assert stored(profile) == {"agent_tools": True}
    async with Harness(profile, patch=[HTTP_OFF]) as h:
        assert registered(h) == WEB and h.get("web").settings()["agent_tools"] is True
