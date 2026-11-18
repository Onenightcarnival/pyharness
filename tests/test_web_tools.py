"""Web tools: HTML to text, web_fetch and web_search over a mocked transport, the optional ``web`` bundle."""

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


async def test_tools_over_mock_transport_and_optional_bundle(home, monkeypatch):
    profile = Profile.init("web", home=str(home))
    assert "web" in profile.bundles()  # optional bundle: on by default
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
        # Optional bundle: switchable through the API, not removable; built-in bundles stay read-only.
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=h.get("http").app), base_url="http://t", timeout=120
        ) as c:
            listed = {b["bundle"]: b for b in (await c.get("/api/plugins")).json()["bundles"]}
            assert (
                listed["web"]["optional"] is True
                and listed["web"]["enabled"] is True
                and listed["web"]["title"] == "Web"
            )
            assert listed["base"]["optional"] is False
            r = await c.put("/api/plugins/bundles/web", json={"enabled": False})
            assert r.status_code == 200 and r.json()["application"] == "saved-restart-required", r.text
            assert (await c.delete("/api/plugins/bundles/web")).status_code == 409
            assert (await c.put("/api/plugins/bundles/base", json={"enabled": False})).status_code == 409
    manifest = yaml.safe_load(profile.manifest_path.read_text())
    assert manifest["disabled"] == ["web"] and "web" not in manifest["bundles"]
    assert "web" not in profile.bundles()
    assert profile.set_bundle_enabled("web", True) and "web" in profile.bundles()
    assert yaml.safe_load(profile.manifest_path.read_text())["disabled"] == []
