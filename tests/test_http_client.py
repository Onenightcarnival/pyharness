"""
HTTP client: the wire helpers, the three stores, the request engine over a mocked transport, the agent tools and
the management routes.
"""

from __future__ import annotations

import asyncio
import base64
import json
import stat
from pathlib import Path
from typing import Any

import httpx
import pytest

from pyharness import Harness, Profile
from pyharness_http_client.engine import (
    HttpEngine,
    PolicyError,
    SendOptions,
    build_url,
    host_matches,
    is_private_address,
    is_textual,
    mask_secrets,
)
from pyharness_http_client.protocol import SseParser, join_url, parse_sse, substitute
from pyharness_http_client.store import (
    HistoryStore,
    RequestStore,
    StoreError,
    TargetStore,
    normalize_auth,
    normalize_base_url,
    secrets_of,
    summarize,
    usable_request_auth,
)
from pyharness_http_client.tools import build_tools, render_exchange, to_output

HTTP_OFF = {"id": "http", "config": {"serve": False}}
ORIGIN = "http://api.test"
PANEL = SendOptions(source="panel")
SSE_FRAMES = [
    ": hello\n\n",
    'event: start\ndata: {"n":0}\n\n',
    "data: token {auth}\n\n",
    "id: 7\ndata: line one\ndata: line two\n\n",
    "data: [DONE]\n\n",
]


def exchange(entry_id: str, target_id: str, at: int) -> dict[str, Any]:
    request = {
        "method": "GET",
        "url": "https://x/",
        "path": "/",
        "query": {},
        "headers": {},
        "body": "",
        "bodyTruncated": False,
    }
    return {"id": entry_id, "at": at, "targetId": target_id, "targetName": "t", "source": "panel", "request": request}


def rejects(action: Any, message: str, error: type[Exception] = StoreError) -> None:
    with pytest.raises(error, match=message):
        action()


# ---------------------------------------------------------------------- wire helpers
def test_protocol_helpers():
    assert substitute("/users/{{ id }}/x{{missing}}", {"id": "42"}) == "/users/42/x{{missing}}"
    base = "https://api.example.com/v1"
    assert (
        str(join_url(base, "/users/42?expand=1", {"page": "2"}))
        == "https://api.example.com/v1/users/42?expand=1&page=2"
    )
    assert str(join_url(base, "users", {})) == "https://api.example.com/v1/users"
    assert str(join_url(base, "", {})) == "https://api.example.com/v1"
    assert str(join_url("https://api.example.com", "", {})) == "https://api.example.com/"
    assert str(join_url(base, "https://cdn.example.com/a b", {})) == "https://cdn.example.com/a%20b"
    assert str(join_url(base, "x", [("ids", "1"), ("ids", "2")])) == "https://api.example.com/v1/x?ids=1&ids=2"
    # Without a base URL the path is the whole URL; a missing scheme is http for local literals, https otherwise.
    assert str(join_url("", "127.0.0.1:8080/x", {})) == "http://127.0.0.1:8080/x"
    assert str(join_url("", "api.example.com/users", {})) == "https://api.example.com/users"
    rejects(lambda: join_url(base, "ftp://x/", {}), r"http\(s\)", ValueError)
    rejects(lambda: join_url(base, "https://u:p@x/", {}), "credentials", ValueError)
    rejects(lambda: join_url("", "", {}), "URL is required", ValueError)
    rejects(lambda: join_url("", "/users", {}), "full URL", ValueError)
    events = parse_sse("".join(SSE_FRAMES) + "retry: 5\r\ndata: last")
    assert [(e["event"], e["data"]) for e in events] == [
        ("start", '{"n":0}'),
        ("", "token {auth}"),
        ("", "line one\nline two"),
        ("", "[DONE]"),
        ("", "last"),
    ]
    assert events[2]["id"] == "7" and events[4]["retry"] == 5
    # A CR that ends a chunk waits for the rest of a CRLF.
    parser = SseParser()
    assert parser.push("data: a\r") == [] and parser.push("\n\r\ndata: b\n\n") == [
        {"event": "", "data": "a"},
        {"event": "", "data": "b"},
    ]


def test_engine_helpers():
    assert host_matches("api.example.com", "api.example.com") and host_matches("a.b.example.com", "*.example.com")
    assert not host_matches("example.com", "*.example.com") and not host_matches("notexample.com", "*.example.com")
    private = ["127.0.0.1", "10.1.2.3", "172.16.0.1", "192.168.1.1", "169.254.1.1", "100.64.0.1", "0.0.0.0"]
    private += ["::1", "fe80::1", "fc00::1", "::ffff:10.0.0.1", "224.0.0.1", "[::1]"]
    assert all(is_private_address(address) for address in private)
    assert not any(is_private_address(a) for a in ("8.8.8.8", "172.32.0.1", "2606:4700::1", "1.1.1.1", "example.com"))
    assert is_textual("application/json", b"") and is_textual("application/vnd.api+json", b"")
    assert not is_textual("image/png", b"") and is_textual("", b"hi") and not is_textual("", b"h\0i")
    assert mask_secrets("Bearer tok/123 and tok%2F123 x", ["tok/123"]) == "Bearer •••••• and •••••• x"
    assert mask_secrets("ab", ["ab"]) == "ab"
    target = {"baseUrl": "https://api.example.com/v1"}
    assert str(build_url(target, "users", {})) == "https://api.example.com/v1/users"
    rejects(lambda: build_url(target, "ftp://x/", {}), r"http\(s\)", PolicyError)


# ---------------------------------------------------------------------- stores
def test_target_fields():
    assert normalize_base_url("https://api.example.com/v1/") == "https://api.example.com/v1"
    assert normalize_base_url("http://localhost:8080") == "http://localhost:8080"
    for bad in ("ftp://x", "https://u:p@x.test", "https://x.test/?a=1", "not a url", ""):
        rejects(lambda bad=bad: normalize_base_url(bad), "baseUrl")
    assert normalize_auth(None) == {"type": "none"}
    assert normalize_auth({"type": "bearer", "token": "abc"}) == {"type": "bearer", "token": "abc"}
    rejects(lambda: normalize_auth({"type": "bearer", "token": ""}), "auth.token is required")
    kept = {"type": "bearer", "token": "kept"}
    assert normalize_auth({"type": "bearer", "token": ""}, kept) == kept
    other = {"type": "header", "name": "X", "value": "v"}
    rejects(lambda: normalize_auth({"type": "bearer", "token": ""}, other), "auth.token is required")
    rejects(lambda: normalize_auth({"type": "basic", "username": "a:b", "password": "p"}), "username")
    rejects(lambda: normalize_auth({"type": "header", "name": "Host", "value": "v"}), "transport")
    rejects(lambda: normalize_auth({"type": "header", "name": "bad name", "value": "v"}), "header name")
    rejects(lambda: normalize_auth({"type": "oauth"}), "auth.type")
    pair = base64.b64encode(b"u:p").decode()
    assert secrets_of({"type": "basic", "username": "u", "password": "p"}) == ["p", pair]
    assert usable_request_auth({"type": "bearer", "token": ""}) is None
    assert usable_request_auth({"type": "header", "name": "Host", "value": "x"}) is None
    query = {"type": "query", "name": "k", "value": "v"}
    assert usable_request_auth(query) == query


def test_target_store(tmp_path):
    store = TargetStore(tmp_path / "targets.json")
    auth = {"type": "bearer", "token": "secret-token"}
    a = store.create(
        {
            "baseUrl": "https://api.example.com/v1/",
            "auth": auth,
            "headers": {"Accept": "application/json"},
            "variables": {"userId": "42"},
        }
    )
    assert (a["name"], a["baseUrl"], a["timeoutMs"], a["allowMutations"]) == (
        "api.example.com",
        "https://api.example.com/v1",
        30_000,
        False,
    )
    b = store.create({"baseUrl": "https://api.example.com"})
    assert b["name"] == "api.example.com 2" and stat.S_IMODE(store.path.stat().st_mode) == 0o600
    summary = summarize(a)
    assert summary["auth"] == {"type": "bearer", "hint": "sec…en"} and "secret-token" not in json.dumps(summary)
    assert store.find("API.EXAMPLE.COM")["id"] == a["id"] and store.find(b["id"])["name"] == b["name"]
    assert "secret-token" in store.path.read_text() and store.find("nope") is None
    assert store.create({"baseUrl": "http://127.0.0.1:8080"})["name"] == "127.0.0.1-8080"
    for payload, message in (
        ({"headers": {"Host": "evil"}}, "transport"),
        ({"headers": {"X-A": "a\r\nb"}}, "line breaks"),
        ({"variables": {"1bad": "x"}}, "invalid name"),
        ({"allowedHosts": ["bad host"]}, "hostname"),
        ({"timeoutMs": 10}, "timeoutMs"),
        ({"timeoutMs": None}, "timeoutMs"),
        ({"name": "a/b"}, "name may contain"),
    ):
        rejects(lambda payload=payload: store.create({"baseUrl": "https://x.test", **payload}), message)
    hosts = store.create(
        {"baseUrl": "https://x.test", "allowedHosts": ["CDN.Example.com.", "*.example.net", "cdn.example.com"]}
    )
    assert hosts["allowedHosts"] == ["cdn.example.com", "*.example.net"]
    # Update merges, keeps an empty secret, renames uniquely; a write notifies subscribers.
    first = store.create(
        {"baseUrl": "https://a.test", "name": "A", "auth": {"type": "header", "name": "X-Key", "value": "k1"}}
    )
    store.create({"baseUrl": "https://b.test", "name": "B"})
    updated = store.update(
        first["id"], {"name": "b", "auth": {"type": "header", "name": "X-Key", "value": ""}, "allowMutations": True}
    )
    assert updated["name"] == "b 2" and updated["auth"] == {"type": "header", "name": "X-Key", "value": "k1"}
    assert updated["allowMutations"] is True and updated["baseUrl"] == "https://a.test"
    rejects(lambda: store.update("missing", {}), "not found")
    count = len(store.list())
    store.delete(first["id"])
    assert len(store.list()) == count - 1
    events: list[int] = []
    store.subscribe(lambda: events.append(1))
    store.set_settings({"agentTools": True})
    assert events == [1] and store.settings()["agentTools"] is True
    rejects(lambda: store.set_settings({"historyLimit": 5}), "historyLimit")
    rejects(lambda: store.set_settings({"historyLimit": None}), "historyLimit")
    rejects(lambda: store.update(hosts["id"], {"timeoutMs": None}), "timeoutMs")
    assert store.set_settings({"historyLimit": 50})["historyLimit"] == 50
    # A fresh instance reads the file; an unreadable file is set aside.
    assert TargetStore(store.path).settings() == {"agentTools": True, "historyLimit": 50}
    store.path.write_text("{oops")
    assert TargetStore(store.path).list() == [] and list(tmp_path.glob("targets.json.corrupt-*"))


def test_history_store(tmp_path):
    limit = {"value": 4}
    history = HistoryStore(tmp_path / "history.jsonl", lambda: limit["value"])
    for i in range(7):
        history.add(exchange(f"e{i}", "a" if i % 2 == 0 else "b", i))
    # Seven entries exceed the limit by half: the seventh add compacts to the last four.
    assert [e["id"] for e in history.list()] == ["e6", "e5", "e4", "e3"]
    assert [e["id"] for e in history.list("a")] == ["e6", "e4"] and len(history.list(None, 2)) == 2
    assert len(history.path.read_text().strip().split("\n")) == 4 and stat.S_IMODE(history.path.stat().st_mode) == 0o600
    assert history.clear(entry_id="e5") == 1 and history.clear(target_id="a") == 2
    assert [e["id"] for e in history.list()] == ["e3"]
    limit["value"] = 10
    again = HistoryStore(history.path, lambda: limit["value"])
    assert [e["id"] for e in again.list()] == ["e3"] and again.clear() == 1 and again.list() == []


def test_request_store(tmp_path):
    path = tmp_path / "requests.json"
    store = RequestStore(path)
    rejects(lambda: store.create({}), "targetId is required")
    a = store.create({"targetId": "t1"})
    defaults = {"name": "", "method": "GET", "path": "", "bodyMode": "none", "query": [], "auth": {"type": "none"}}
    assert {k: a[k] for k in defaults} == defaults
    rows = [{"key": "page", "value": "1", "enabled": False}, {"key": "x"}]
    b = store.create(
        {
            "targetId": "t1",
            "name": " List users ",
            "method": "post",
            "path": "/users",
            "query": rows,
            "bodyMode": "json",
            "body": "{}",
        }
    )
    assert (b["name"], b["method"]) == ("List users", "POST")
    assert b["query"] == [{"key": "page", "value": "1", "enabled": False}, {"key": "x", "value": "", "enabled": True}]
    store.create({"targetId": "t2", "path": "/other"})
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    headers = [{"key": "Accept", "value": "application/json", "enabled": True}]
    updated = store.update(a["id"], {"path": "/users/{{id}}", "headers": headers})
    assert (updated["path"], updated["method"], updated["targetId"]) == ("/users/{{id}}", "GET", "t1")
    for patch, message in (
        ({"method": "BREW"}, "unsupported method"),
        ({"bodyMode": "xml"}, "bodyMode"),
        ({"body": "x" * (256 * 1024 + 1)}, "body"),
        ({"name": "a\0b"}, "name"),
        ({"auth": {"type": "oauth"}}, "auth.type"),
        ({"auth": {"type": "bearer", "token": "a\nb"}}, "line breaks"),
        ({"targetId": " "}, "targetId"),
    ):
        rejects(lambda patch=patch: store.update(a["id"], patch), message)
    rejects(lambda: store.update("missing", {}), "not found")
    assert [r["id"] for r in store.list("t1")] == [a["id"], b["id"]]
    # Auth is stored as typed, incomplete fields included; an update with targetId moves the request.
    assert store.update(a["id"], {"auth": {"type": "bearer", "token": ""}})["auth"] == {"type": "bearer", "token": ""}
    moved = store.update(b["id"], {"targetId": "direct", "path": "https://api.example.com/v1/users"})
    assert moved["targetId"] == "direct" and [r["id"] for r in store.list("t1")] == [a["id"]]
    again = RequestStore(path)
    assert again.get(a["id"])["path"] == "/users/{{id}}" and len(again.list()) == 3
    again.delete(b["id"])
    assert again.delete_by_target("t1") == 1 and [r["targetId"] for r in again.list()] == ["t2"]


# ---------------------------------------------------------------------- engine
async def sse_body(auth: str, frames: list[str], pause: float = 0.01) -> Any:
    for frame in frames:
        await asyncio.sleep(pause)
        yield frame.replace("{auth}", auth).encode()


async def forever() -> Any:
    n = 0
    while True:
        await asyncio.sleep(0.04)
        yield f"data: tick {n}\n\n".encode()
        n += 1


async def handler(request: httpx.Request) -> httpx.Response:
    path = request.url.path
    if request.url.host == "dead.test":
        raise httpx.ConnectError("connection refused")
    if path == "/v1/redirect":
        return httpx.Response(302, headers={"location": "/v1/echo?from=redirect"})
    if path == "/v1/redirect-out":
        return httpx.Response(302, headers={"location": "https://other.invalid/x"})
    if path == "/v1/redirect-post":
        return httpx.Response(303, headers={"location": "/v1/echo"})
    if path == "/v1/redirect-cdn":
        return httpx.Response(307, headers={"location": "https://cdn.test/v1/echo?api_key=leak&keep=1"})
    if path == "/v1/big":
        return httpx.Response(200, headers={"content-type": "text/plain"}, content=b"x" * 5000)
    if path == "/v1/binary":
        return httpx.Response(200, headers={"content-type": "application/octet-stream"}, content=bytes([0, 1, 2, 3]))
    if path == "/v1/gbk":
        return httpx.Response(
            200, headers={"content-type": "text/plain; charset=gbk"}, content=bytes([0xC4, 0xE3, 0xBA, 0xC3])
        )
    if path == "/v1/slow":
        await asyncio.sleep(1.5)
        return httpx.Response(200, content=b"late")
    if path == "/v1/sse":
        frames = sse_body(request.headers.get("authorization", ""), SSE_FRAMES)
        return httpx.Response(200, headers={"content-type": "text/event-stream; charset=utf-8"}, content=frames)
    if path == "/v1/sse-forever":
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=forever())
    seen = {
        "method": request.method,
        "url": request.url.raw_path.decode(),
        "host": request.url.host,
        "headers": dict(request.headers),
        "body": request.content.decode(),
    }
    return httpx.Response(200 if path == "/v1/echo" else 404, json=seen)


@pytest.fixture
def rig(tmp_path: Path) -> Any:
    store = TargetStore(tmp_path / "targets.json")
    history = HistoryStore(tmp_path / "history.jsonl", lambda: 100)
    engine = HttpEngine(store, history, httpx.MockTransport(handler))

    def target(**fields: Any) -> dict[str, Any]:
        return store.create({"baseUrl": f"{ORIGIN}/v1", "allowPrivate": True, **fields})

    return store, history, engine, target


async def test_engine_request_and_masking(rig):
    _store, history, engine, target = rig
    t = target(
        auth={"type": "bearer", "token": "super-secret-token"}, headers={"X-Fixed": "yes"}, variables={"id": "42"}
    )
    request = {"method": "GET", "path": "/echo/{{id}}", "query": {"q": "{{id}}"}, "headers": {"X-Req": "r"}}
    sent = await engine.send(t["name"], request, SendOptions(source="agent"))
    assert "error" not in sent and sent["response"]["status"] == 404
    seen = json.loads(sent["response"]["body"])
    assert seen["url"] == "/v1/echo/42?q=42" and seen["headers"]["x-fixed"] == "yes" and seen["headers"]["x-req"] == "r"
    # The echoed Authorization header is masked in the body handed back.
    assert seen["headers"]["authorization"] == "Bearer ••••••" and "super-secret-token" not in json.dumps(sent)
    assert sent["request"]["url"] == f"{ORIGIN}/v1/echo/42?q=42" and sent["request"]["query"] == [["q", "{{id}}"]]
    recorded = history.list(t["id"])[0]
    assert recorded["id"] == sent["id"] and recorded["source"] == "agent"
    # POST defaults content-type to JSON; HEAD drops the body; query auth is masked in the URL.
    keyed = target(auth={"type": "query", "name": "api_key", "value": "qsecret99"})
    posted = await engine.send(keyed["id"], {"method": "POST", "path": "echo", "body": '{"a":1}'}, PANEL)
    seen = json.loads(posted["response"]["body"])
    assert (seen["method"], seen["body"], seen["url"]) == ("POST", '{"a":1}', "/v1/echo?api_key=••••••")
    assert seen["headers"]["content-type"].startswith("application/json")
    assert posted["request"]["url"] == f"{ORIGIN}/v1/echo?api_key=••••••"
    head = await engine.send(keyed["id"], {"method": "HEAD", "path": "echo", "body": "ignored"}, PANEL)
    assert head["response"]["status"] == 200 and json.loads(head["response"]["body"])["body"] == ""
    # Sent headers are recorded masked, with lower-case names; the composed headers stay as typed.
    sent = await engine.send(
        t["id"], {"method": "POST", "path": "echo", "headers": {"X-Req": "r"}, "body": "plain"}, PANEL
    )
    wire = sent["request"]["sentHeaders"]
    assert sent["request"]["headers"] == {"X-Req": "r"} and wire["authorization"] == "Bearer ••••••"
    assert (wire["x-fixed"], wire["x-req"], wire["accept"]) == ("yes", "r", "*/*") and wire["content-type"].startswith(
        "text/plain"
    )
    # The id of a saved request is recorded; a malformed one is dropped.
    tagged = await engine.send(t["id"], {"method": "GET", "path": "echo", "requestId": "abc123def456"}, PANEL)
    assert tagged["requestId"] == "abc123def456" and history.list(t["id"])[0]["requestId"] == "abc123def456"
    assert "requestId" not in await engine.send(
        t["id"], {"method": "GET", "path": "echo", "requestId": "../etc"}, PANEL
    )
    await engine.aclose()


async def test_engine_redirects_and_host_policy(rig):
    store, _history, engine, target = rig
    t = target(auth={"type": "bearer", "token": "redirect-token"})
    followed = await engine.send(t["id"], {"method": "GET", "path": "redirect"}, PANEL)
    assert followed["response"]["status"] == 200 and followed["response"]["redirects"] == [
        f"{ORIGIN}/v1/echo?from=redirect"
    ]
    assert json.loads(followed["response"]["body"])["headers"]["authorization"] == "Bearer ••••••"
    post = json.loads(
        (await engine.send(t["id"], {"method": "POST", "path": "redirect-post", "body": '{"x":1}'}, PANEL))["response"][
            "body"
        ]
    )
    assert (post["method"], post["body"]) == ("GET", "") and "content-type" not in post["headers"]
    out = await engine.send(t["id"], {"method": "GET", "path": "redirect-out"}, PANEL)
    assert "response" not in out and "redirect to 'other.invalid' is not allowed" in out["error"]
    # Another origin on an allowed host gets no credentials: neither the header nor the query parameter.
    keyed = target(auth={"type": "query", "name": "api_key", "value": "qsecret99"}, allowedHosts=["cdn.test"])
    crossed = json.loads(
        (await engine.send(keyed["id"], {"method": "GET", "path": "redirect-cdn"}, PANEL))["response"]["body"]
    )
    assert crossed["host"] == "cdn.test" and crossed["url"] == "/v1/echo?keep=1"
    carried = target(auth={"type": "header", "name": "X-Key", "value": "header-secret"}, allowedHosts=["*.test"])
    crossed = json.loads(
        (
            await engine.send(
                carried["id"], {"method": "GET", "path": "redirect-cdn", "headers": {"Cookie": "sid=abc12345"}}, PANEL
            )
        )["response"]["body"]
    )
    assert "x-key" not in crossed["headers"] and "cookie" not in crossed["headers"]
    # An absolute URL must be on the base host or an allowed host; private addresses need the switch.
    hosts = target(allowedHosts=["*.invalid"])
    assert (
        "not allowed"
        in (await engine.send(hosts["id"], {"method": "GET", "path": "https://example.com/"}, PANEL))["error"]
    )
    assert (await engine.send(hosts["id"], {"method": "GET", "path": f"{ORIGIN}/v1/echo"}, PANEL))["response"][
        "status"
    ] == 200
    guarded = store.create({"baseUrl": "http://127.0.0.1:9/v1"})
    assert "private" in (await engine.send(guarded["id"], {"method": "GET", "path": "echo"}, PANEL))["error"]
    local = store.create({"baseUrl": "http://localhost:1/v1"})
    assert "loopback" in (await engine.send(local["id"], {"method": "GET", "path": ""}, PANEL))["error"]
    await engine.aclose()


async def test_engine_bodies_timeouts_and_errors(rig):
    store, history, engine, target = rig
    t = target()
    capped = (
        await engine.send(t["id"], {"method": "GET", "path": "big"}, SendOptions(source="panel", max_body_bytes=100))
    )["response"]
    assert capped["bodyTruncated"] is True and capped["bodyBytes"] == 100 and len(capped["body"]) == 100
    binary = (await engine.send(t["id"], {"method": "GET", "path": "binary"}, PANEL))["response"]
    assert binary["binary"] is True and binary["body"] == "" and binary["bodyBytes"] == 4 and "bodyBase64" not in binary
    # A binary body comes back whole as base64 for the live page response on request, never in the history.
    kept = await engine.send(
        t["id"], {"method": "GET", "path": "binary"}, SendOptions(source="panel", keep_binary=True)
    )
    assert kept["response"]["bodyBase64"] == base64.b64encode(bytes([0, 1, 2, 3])).decode()
    assert "bodyBase64" not in history.list(t["id"])[0]["response"]
    text = await engine.send(t["id"], {"method": "GET", "path": "echo"}, SendOptions(source="panel", keep_binary=True))
    assert "bodyBase64" not in text["response"]
    assert (await engine.send(t["id"], {"method": "GET", "path": "gbk"}, PANEL))["response"]["body"] == "你好"
    slow = target(timeoutMs=1000)
    assert (await engine.send(slow["id"], {"method": "GET", "path": "slow"}, PANEL))[
        "error"
    ] == "timed out after 1000 ms"
    dead = store.create({"baseUrl": "http://dead.test/v1", "allowPrivate": True})
    assert "connection refused" in (await engine.send(dead["id"], {"method": "GET", "path": ""}, PANEL))["error"]
    checked = await engine.test(t["id"])
    assert checked["ok"] is True and checked["status"] == 404 and (await engine.test(dead["id"]))["ok"] is False
    # Shape errors and unknown targets raise before anything is sent or recorded.
    before = len(history.list(t["id"]))
    for ref, request, message in (
        (t["id"], {"method": "BREW", "path": "/"}, "unsupported method"),
        (t["id"], {"method": "GET", "path": "/", "headers": {"X-A": "a\nb"}}, "line breaks"),
        (t["id"], {"method": "GET", "path": "/", "query": ["x"]}, "object of strings"),
        (t["id"], {"method": "GET", "path": "/", "query": [["a"]]}, "pairs"),
        ("nope", {"method": "GET", "path": "/"}, "not found"),
    ):
        with pytest.raises(PolicyError, match=message):
            await engine.send(ref, request, PANEL)
    assert len(history.list(t["id"])) == before
    # Cancel: the request ends and is recorded as cancelled.
    cancel = asyncio.Event()
    asyncio.get_running_loop().call_later(0.1, cancel.set)
    started = asyncio.get_running_loop().time()
    cancelled = await engine.send(
        t["id"], {"method": "GET", "path": "slow"}, SendOptions(source="panel", cancel=cancel)
    )
    assert cancelled["error"] == "cancelled" and asyncio.get_running_loop().time() - started < 1.0
    assert history.list(t["id"])[0]["error"] == "cancelled"
    assert (await engine.send(t["id"], {"method": "GET", "path": "echo"}, SendOptions(source="panel", cancel=cancel)))[
        "error"
    ] == "cancelled"
    await engine.aclose()


async def test_engine_direct_scope_and_request_auth(rig):
    _store, history, engine, target = rig
    typed = {"Authorization": "Bearer typed-token-xyz", "X-Api-Key": "key-98765"}
    direct = await engine.send("direct", {"method": "GET", "path": f"{ORIGIN}/v1/echo?x=1", "headers": typed}, PANEL)
    assert "error" not in direct and direct["targetId"] == "direct" and direct["response"]["status"] == 200
    seen = json.loads(direct["response"]["body"])["headers"]
    assert seen["authorization"] == "Bearer ••••••" and seen["x-api-key"] == "••••••"
    assert direct["request"]["headers"]["Authorization"] == "Bearer ••••••"
    assert "typed-token-xyz" not in json.dumps(direct) and "key-98765" not in json.dumps(direct)
    assert history.list("direct")[0]["id"] == direct["id"]
    # The agent cannot send through the direct scope.
    with pytest.raises(PolicyError, match="not found"):
        await engine.send("direct", {"method": "GET", "path": f"{ORIGIN}/v1/echo"}, SendOptions(source="agent"))
    assert (await engine.send("direct", {"method": "GET", "path": "api.test/v1/echo"}, PANEL))["request"][
        "url"
    ] == "https://api.test/v1/echo"
    assert "URL is required" in (await engine.send("direct", {"method": "GET", "path": ""}, PANEL))["error"]
    assert "full URL" in (await engine.send("direct", {"method": "GET", "path": "/users"}, PANEL))["error"]
    # Query pairs keep repeated names; a blank name is dropped.
    t = target()
    repeated = await engine.send(
        t["id"], {"method": "GET", "path": "echo", "query": [["ids", "1"], ["ids", "2"], [" ", "x"]]}, PANEL
    )
    assert json.loads(repeated["response"]["body"])["url"] == "/v1/echo?ids=1&ids=2"
    assert repeated["request"]["query"] == [["ids", "1"], ["ids", "2"]]
    assert "abc123456" not in json.dumps(
        await engine.send(t["id"], {"method": "GET", "path": "echo", "headers": {"Cookie": "sid=abc123456"}}, PANEL)
    )
    # A request's own auth applies when the page sends it and the target has none.
    own = {"type": "bearer", "token": "request-level-token"}
    with_auth = await engine.send(t["id"], {"method": "GET", "path": "echo", "auth": own}, PANEL)
    assert with_auth["request"]["sentHeaders"][
        "authorization"
    ] == "Bearer ••••••" and "request-level-token" not in json.dumps(with_auth)
    basic = {"type": "basic", "username": "u", "password": "pw-secret"}
    assert (await engine.send("direct", {"method": "GET", "path": f"{ORIGIN}/v1/echo", "auth": basic}, PANEL))[
        "request"
    ]["sentHeaders"]["authorization"] == "Basic ••••••"
    keyed = {"type": "query", "name": "key", "value": "q-secret-1"}
    assert (await engine.send(t["id"], {"method": "GET", "path": "echo", "auth": keyed}, PANEL))["request"][
        "url"
    ] == f"{ORIGIN}/v1/echo?key=••••••"
    incomplete = await engine.send(
        t["id"], {"method": "GET", "path": "echo", "auth": {"type": "bearer", "token": ""}}, PANEL
    )
    assert "authorization" not in incomplete["request"]["sentHeaders"]
    agent = await engine.send(t["id"], {"method": "GET", "path": "echo", "auth": own}, SendOptions(source="agent"))
    assert "authorization" not in agent["request"]["sentHeaders"]
    guarded = target(auth={"type": "header", "name": "X-Key", "value": "target-key-1"})
    shadowed = (await engine.send(guarded["id"], {"method": "GET", "path": "echo", "auth": own}, PANEL))["request"][
        "sentHeaders"
    ]
    assert "authorization" not in shadowed and shadowed["x-key"] == "••••••"
    await engine.aclose()


async def test_engine_event_streams(rig):
    _store, history, engine, target = rig
    t = target(auth={"type": "bearer", "token": "stream-secret-9"})
    heads: list[int] = []
    seen: list[dict[str, Any]] = []
    options = SendOptions(
        source="panel",
        on_stream_start=lambda head: heads.append(head["status"]),
        on_stream_event=lambda event, at: seen.append({**event, "at": at}),
    )
    sent = await engine.send(t["id"], {"method": "GET", "path": "sse"}, options)
    assert "error" not in sent and heads == [200]
    assert [(e["event"], e["data"]) for e in seen] == [
        ("start", '{"n":0}'),
        ("", "token Bearer ••••••"),
        ("", "line one\nline two"),
        ("", "[DONE]"),
    ]
    assert seen[2]["id"] == "7" and seen[0]["at"] <= seen[3]["at"]
    response = sent["response"]
    assert (
        response["stream"]["ended"] == "complete"
        and len(response["stream"]["times"]) == 4
        and response["binary"] is False
    )
    assert response["body"].startswith(": hello\n\nevent: start") and "stream-secret-9" not in json.dumps(sent)
    assert len(history.list(t["id"])[0]["response"]["stream"]["times"]) == 4
    # A stop ends the stream with what arrived instead of failing the request.
    fast = target(timeoutMs=1000)
    stop = asyncio.Event()
    count = {"n": 0}

    def on_event(event: dict[str, Any], at: int) -> None:
        count["n"] += 1
        if count["n"] == 3:
            stop.set()

    stopped = await engine.send(
        fast["id"],
        {"method": "GET", "path": "sse-forever"},
        SendOptions(source="panel", cancel=stop, on_stream_event=on_event),
    )
    assert "error" not in stopped and stopped["response"]["stream"]["ended"] == "cancelled"
    assert len(stopped["response"]["stream"]["times"]) >= 3 and stopped["response"]["body"].startswith(
        "data: tick 0\n\ndata: tick 1"
    )
    # The page's timeout restarts with every chunk, so a live stream outlasts it; the cap ends it.
    capped = (
        await engine.send(
            fast["id"], {"method": "GET", "path": "sse-forever"}, SendOptions(source="panel", max_body_bytes=500)
        )
    )["response"]
    assert capped["stream"]["ended"] == "limit" and capped["bodyTruncated"] is True and capped["bodyBytes"] == 500
    assert capped["durationMs"] > 1000
    # The agent's timeout covers the whole stream.
    agent = await engine.send(fast["id"], {"method": "GET", "path": "sse-forever"}, SendOptions(source="agent"))
    assert (
        "error" not in agent
        and agent["response"]["stream"]["ended"] == "timeout"
        and agent["response"]["durationMs"] < 1600
    )
    await engine.aclose()


# ---------------------------------------------------------------------- tools
class Rig:
    def __init__(self, store: TargetStore, history: HistoryStore, engine: HttpEngine) -> None:
        self.store, self.history, self.engine = store, history, engine


async def test_tools(rig):
    store, history, engine, _target = rig
    read_only = store.create(
        {
            "baseUrl": "https://ro.example.com/api",
            "auth": {"type": "bearer", "token": "ro-token-value"},
            "allowPrivate": True,
            "variables": {"id": "1"},
        }
    )
    store.create(
        {
            "baseUrl": "https://rw.example.com",
            "name": "rw",
            "allowMutations": True,
            "allowPrivate": True,
            "allowedHosts": ["cdn.test"],
        }
    )
    tools = {t.name: t for t in build_tools(Rig(store, history, engine))}
    listed = await tools["http_targets"].ainvoke({})
    assert "ro-token-value" not in listed
    assert "ro.example.com | https://ro.example.com/api | bearer | GET/HEAD/OPTIONS only | {{id}} | -" in listed
    assert "rw | https://rw.example.com | none | allowed (confirm required) | - | cdn.test" in listed
    request = tools["http_request"]
    got = await request.ainvoke(
        {"target": read_only["name"], "method": "get", "path": "/v1/echo", "query": {"page": "1"}}
    )
    assert (
        got.startswith("GET https://ro.example.com/api/v1/echo?page=1 → 404")
        and '"authorization":"Bearer ••••••"' in got
    )
    refused = await request.ainvoke({"target": read_only["name"], "method": "POST", "path": "/users", "confirm": True})
    assert refused.startswith("request failed: refused:") and "GET/HEAD/OPTIONS only" in refused
    assert "confirm must be true" in await request.ainvoke({"target": "rw", "method": "DELETE", "path": "/users/1"})
    before = len(history.list())
    posted = await request.ainvoke(
        {"target": "rw", "method": "POST", "path": "/v1/echo", "body": '{"a":1}', "confirm": True}
    )
    assert posted.startswith("POST https://rw.example.com/v1/echo → 200") and len(history.list()) == before + 1
    assert "not found" in await request.ainvoke({"target": "missing", "method": "GET", "path": "/"})
    assert "unsupported method" in await request.ainvoke({"target": "rw", "method": "BREW", "path": "/"})
    assert "query.page must be a string" in await request.ainvoke(
        {"target": "rw", "method": "GET", "path": "/", "query": {"page": 1}}
    )
    past = await tools["http_history"].ainvoke({"target": "rw"})
    assert "[agent] rw: POST https://rw.example.com/v1/echo → 200" in past and 'request body: {"a":1}' in past
    everything = await tools["http_history"].ainvoke({})
    assert sum(line.startswith("20") for line in everything.splitlines()) == 2
    assert "[agent] ro.example.com: GET" in everything
    assert "not found" in await tools["http_history"].ainvoke({"target": "nope"})
    # Requests sent without a target stay out of the agent's view and cannot be called.
    await engine.send("direct", {"method": "GET", "path": "https://direct.example.com/private"}, PANEL)
    assert len(history.list("direct")) == 1 and "direct.example.com" not in await tools["http_history"].ainvoke({})
    assert "not found" in await tools["http_history"].ainvoke({"target": "direct"})
    assert "not found" in await request.ainvoke(
        {"target": "direct", "method": "GET", "path": "https://direct.example.com/"}
    )
    assert (
        render_exchange("GET", {"ok": False, "error": "boom", "url": "https://x/"})
        == "request failed (GET https://x/): boom"
    )
    image = {
        **exchange("i", "t", 0),
        "response": {
            "status": 200,
            "statusText": "OK",
            "headers": {},
            "contentType": "image/png",
            "bodyBytes": 2048,
            "body": "",
            "bodyTruncated": False,
            "binary": True,
            "durationMs": 12,
            "redirects": [],
        },
    }
    assert "image/png · 2.0 KiB\n[binary body omitted]" in render_exchange("GET", to_output(image))
    empty = Rig(TargetStore(store.path.with_name("none.json")), history, engine)
    assert "no HTTP targets configured" in await build_tools(empty)[0].ainvoke({})
    await engine.aclose()


# ---------------------------------------------------------------------- harness
async def test_http_client_in_the_harness(home, tmp_path):
    profile = Profile.init("web", home=str(home))
    patch = [HTTP_OFF, {"id": "http-client", "config": {"data_dir": str(tmp_path / "hc")}, "merge": True}]
    async with Harness(profile, patch=patch) as h:
        service = h.get("httpClient")
        await service.engine.aclose()
        service.engine.client = httpx.AsyncClient(
            transport=httpx.MockTransport(handler), follow_redirects=False, timeout=None
        )
        names = lambda: {t.name for t in h.get("tools").list()}  # noqa: E731
        assert not {"http_targets", "http_request", "http_history"} & names()
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=h.get("http").app), base_url="http://t") as c:
            api = "/api/http-client"
            assert (await c.get(f"{api}/targets")).json() == {"targets": []}
            assert (await c.get(f"{api}/settings")).json() == {"settings": {"agentTools": False, "historyLimit": 200}}
            auth = {"type": "bearer", "token": "panel-secret-1"}
            created = (
                await c.post(f"{api}/targets", json={"baseUrl": f"{ORIGIN}/v1", "auth": auth, "allowPrivate": True})
            ).json()["target"]
            assert created["name"] == "api.test" and created["auth"] == {"type": "bearer", "hint": "pan…-1"}
            tid = created["id"]
            assert (await c.post(f"{api}/targets", json={"baseUrl": "nope"})).status_code == 400
            patched = (
                await c.patch(f"{api}/targets", params={"id": tid}, json={"name": "main", "variables": {"id": "7"}})
            ).json()["target"]
            assert (
                patched["name"] == "main"
                and patched["variables"] == {"id": "7"}
                and patched["auth"]["type"] == "bearer"
            )
            assert (await c.patch(f"{api}/targets", params={"id": "missing"}, json={})).status_code == 400
            # Saved requests: a target or the direct scope; unknown scopes are refused.
            saved = (
                await c.post(f"{api}/requests", json={"targetId": tid, "name": "one", "path": "/echo/{{id}}"})
            ).json()["request"]
            assert (await c.post(f"{api}/requests", json={"targetId": "ghost"})).status_code == 400
            loose = (await c.post(f"{api}/requests", json={"targetId": "direct", "path": f"{ORIGIN}/v1/echo"})).json()[
                "request"
            ]
            assert [
                r["id"] for r in (await c.get(f"{api}/requests", params={"target": "direct"})).json()["requests"]
            ] == [loose["id"]]
            moved = (
                await c.patch(f"{api}/requests", params={"id": loose["id"]}, json={"targetId": tid, "method": "POST"})
            ).json()["request"]
            assert moved["targetId"] == tid and moved["method"] == "POST"
            assert (
                await c.patch(f"{api}/requests", params={"id": saved["id"]}, json={"method": "BREW"})
            ).status_code == 400
            assert (await c.delete(f"{api}/requests", params={"id": loose["id"]})).json() == {"ok": True}
            # Send: the exchange comes back masked and is recorded; a shape error answers 400.
            body = {"id": tid, "request": {"method": "GET", "path": "/echo/{{id}}", "requestId": saved["id"]}}
            sent = (await c.post(f"{api}/send", json=body)).json()["exchange"]
            assert (
                sent["response"]["status"] == 404
                and sent["requestId"] == saved["id"]
                and "panel-secret-1" not in json.dumps(sent)
            )
            assert json.loads(sent["response"]["body"])["url"] == "/v1/echo/7"
            assert (await c.post(f"{api}/send", json={"id": tid, "request": {"method": "BREW"}})).status_code == 400
            assert (await c.post(f"{api}/send", json={"request": {}})).status_code == 400
            failed = (
                await c.post(
                    f"{api}/send", json={"id": tid, "request": {"method": "GET", "path": "https://elsewhere.test/"}}
                )
            ).json()["exchange"]
            assert "not allowed" in failed["error"]
            # NDJSON: head and events of an event stream as they arrive, then the exchange.
            ndjson = {"accept": "application/x-ndjson"}
            streamed = await c.post(
                f"{api}/send", json={"id": tid, "request": {"method": "GET", "path": "sse"}}, headers=ndjson
            )
            lines = [json.loads(line) for line in streamed.text.splitlines()]
            assert streamed.headers["content-type"].startswith("application/x-ndjson")
            assert [line["type"] for line in lines] == ["head", "event", "event", "event", "event", "done"]
            assert (
                lines[2]["event"]["data"] == "token Bearer ••••••"
                and lines[-1]["exchange"]["response"]["stream"]["ended"] == "complete"
            )
            plain = await c.post(
                f"{api}/send", json={"id": tid, "request": {"method": "GET", "path": "echo"}}, headers=ndjson
            )
            assert [json.loads(line)["type"] for line in plain.text.splitlines()] == ["done"]
            wrong = await c.post(
                f"{api}/send", json={"id": "ghost", "request": {"method": "GET", "path": "/"}}, headers=ndjson
            )
            assert json.loads(wrong.text)["type"] == "error"
            direct = (
                await c.post(
                    f"{api}/send", json={"id": "direct", "request": {"method": "GET", "path": f"{ORIGIN}/v1/echo"}}
                )
            ).json()["exchange"]
            assert direct["targetId"] == "direct" and direct["response"]["status"] == 200
            # History, connection test.
            entries = (await c.get(f"{api}/history", params={"target": tid})).json()["entries"]
            assert [e["request"]["path"] for e in entries] == ["echo", "sse", "https://elsewhere.test/", "/echo/{{id}}"]
            assert (await c.delete(f"{api}/history", params={"id": entries[0]["id"]})).json() == {"removed": 1}
            assert (await c.post(f"{api}/test", json={"id": tid})).json()["result"]["ok"] is True
            assert (await c.post(f"{api}/test", json={"id": "ghost"})).status_code == 400
            # The switch registers the tools and the prompt section, and withdraws them.
            assert (await c.post(f"{api}/settings", json={"agentTools": True, "historyLimit": 20})).json() == {
                "settings": {"agentTools": True, "historyLimit": 20}
            }
            assert {"http_targets", "http_request", "http_history"} <= names() and "HTTP API request tool" in h.get(
                "prompt"
            ).render()
            assert (await c.post(f"{api}/settings", json={"historyLimit": 3})).status_code == 400
            assert (await c.post(f"{api}/settings", json={"agentTools": False})).json()["settings"][
                "agentTools"
            ] is False
            assert not {"http_targets"} & names() and "HTTP API request tool" not in h.get("prompt").render()
            # Deleting a target removes its saved requests and its history.
            assert (await c.delete(f"{api}/targets", params={"id": tid})).json() == {"ok": True}
            assert (await c.get(f"{api}/requests", params={"target": tid})).json() == {"requests": []}
            assert (await c.get(f"{api}/history", params={"target": tid})).json() == {"entries": []}
            assert len((await c.get(f"{api}/history")).json()["entries"]) == 1
            assert (await c.delete(f"{api}/history")).json() == {"removed": 1}
    assert stat.S_IMODE((tmp_path / "hc" / "targets.json").stat().st_mode) == 0o600
