"""Web tools: HTML to text, web_fetch and web_search over a mocked transport, the optional ``web`` bundle."""

from __future__ import annotations

import json

import httpx
import yaml
from pyharness_web_tools import format_search, html_to_text, parse_search_response

from pyharness import Harness, Profile

HTTP_OFF = {"id": "http", "config": {"serve": False}}
PAGE = """<html><head><title>Hello &amp; welcome</title><style>p{}</style><script>alert(1)</script></head>
<body><nav><a href="/about">About</a></nav><h1>Heading</h1><p>First   paragraph with <a href="https://x.test/doc">a link</a>.</p>
<ul><li>one</li><li>two</li></ul><pre>  code\n  block</pre><img alt="diagram"></body></html>"""  # noqa: E501

SEARCH_RESPONSE = {
    "content": [
        {"type": "server_tool_use", "name": "web_search", "input": {"query": "pyharness"}},
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


async def test_tools_over_mock_transport_and_optional_bundle(home, monkeypatch):
    profile = Profile.init("web", home=str(home))
    assert "web" in profile.bundles()  # optional bundle: on by default
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.path.endswith("/messages"):
            assert request.headers["x-api-key"] == "sk-test" and request.headers["anthropic-version"] == "2023-06-01"
            body = json.loads(request.content)
            assert (
                body["tools"][0]["type"] == "web_search_20250305"
                and "pyharness" in body["messages"][0]["content"][0]["text"]
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
        missing = await tools["web_search"].ainvoke({"query": "pyharness"})
        assert missing.startswith("Error:") and "DEEPSEEK_API_KEY" in missing
        assert web.status()["search"]["configured"] is False
        profile.credentials.set("DEEPSEEK_API_KEY", "sk-test")
        out = await tools["web_search"].ainvoke({"query": "pyharness"})
        assert (
            "A says hi. B too." in out
            and "[Result A](https://a.test/1)" in out
            and "[Result B](https://b.test/2)" in out
        )
        assert web.status()["search"]["configured"] is True and web.status()["search"]["source"] == "store"
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
