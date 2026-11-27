"""
HTTP client: the wire helpers, the stores, the request engine over a mocked transport (secret variables, captured
variables and their refresh included), the agent tools and the management routes.
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

from pyxis_harness import Harness, Profile
from pyxis_harness_http_client.capture import parse_json_path, read_path, run_captures
from pyxis_harness_http_client.engine import (
    HttpEngine,
    PolicyError,
    SendOptions,
    build_url,
    host_matches,
    is_expired,
    is_private_address,
    is_textual,
    mask_secrets,
)
from pyxis_harness_http_client.protocol import (
    SseParser,
    blank_capture,
    join_url,
    parse_sse,
    referenced_variables,
    request_input_of,
    substitute,
)
from pyxis_harness_http_client.store import (
    HistoryStore,
    RequestStore,
    StoreError,
    TargetStore,
    ValueStore,
    normalize_auth,
    normalize_base_url,
    secrets_of,
    summarize,
    usable_request_auth,
)
from pyxis_harness_http_client.tools import build_tools, render_exchange, to_output

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
    def __init__(
        self,
        store: TargetStore,
        history: HistoryStore,
        engine: HttpEngine,
        requests: RequestStore | None = None,
        values: ValueStore | None = None,
    ) -> None:
        self.store, self.history, self.engine, self.requests, self.values = store, history, engine, requests, values


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


# ---------------------------------------------------------------------- secret, captured and refreshed variables
class Api:
    """Stub token API: what it saw and how it answers."""

    def __init__(self) -> None:
        self.token_calls = self.api_calls = self.pair_calls = self.issued = self.logins = 0
        self.token_bodies: list[str] = []
        self.valid: set[str] = set()
        self.token_status = 200
        self.token_delay = 0.0
        self.seen: list[tuple[str, dict[str, str]]] = []

    def seen_at(self, path: str) -> dict[str, str]:
        """Headers of the latest request to a path."""
        return next((headers for url, headers in reversed(self.seen) if url.split("?")[0] == path), {})

    async def __call__(self, request: httpx.Request) -> httpx.Response:
        path, url = request.url.path, request.url.raw_path.decode()
        self.seen.append((url, dict(request.headers)))
        if path == "/token":
            self.token_calls += 1
            self.token_bodies.append(request.content.decode())
            await asyncio.sleep(self.token_delay)
            if self.token_status != 200:
                return httpx.Response(self.token_status, json={"error": "nope"})
            self.issued += 1
            self.valid.add(f"access-token-{self.issued}")
            return httpx.Response(200, json={"access_token": f"access-token-{self.issued}", "expires_in": 7200})
        if path == "/login":
            self.logins += 1
            body = {"data": {"access_token": f"secret-token-{self.logins}"}}
            return httpx.Response(200, headers={"x-session": f"sess-{self.logins}"}, json=body)
        if path == "/denied":
            return httpx.Response(403, json={"data": {"access_token": "never"}})
        if path == "/plain":
            return httpx.Response(200, headers={"content-type": "text/plain"}, content=b"plain text")
        if path in ("/stream", "/sse-401"):
            status = 200 if path == "/stream" else 401
            return httpx.Response(status, headers={"content-type": "text/event-stream"}, content=b"data: denied\n\n")
        if path == "/echo":
            return httpx.Response(200, json={"headers": dict(request.headers), "url": url})
        if path == "/pair":
            self.pair_calls += 1
            return httpx.Response(200, json={"first": "pair-first-value", "second": "pair-second-value"})
        if path in ("/a", "/b"):
            return httpx.Response(200, json={"value": f"{path[1:]}-value-1"})
        self.api_calls += 1
        bearer = request.headers.get("authorization", "").removeprefix("Bearer ")
        got = bearer or request.url.params.get("access_token", "")
        if path == "/always-401" or got not in self.valid:
            return httpx.Response(401, json={"error": "invalid token", "got": got})
        return httpx.Response(200, json={"ok": True, "path": path, "got": got})


class Lab:
    """The four stores and an engine over the stub API; also the host of the agent tools."""

    def __init__(self, base: Path) -> None:
        self.api = Api()
        self.store = TargetStore(base / "targets.json")
        self.requests = RequestStore(base / "requests.json")
        self.history = HistoryStore(base / "history.jsonl", lambda: 500)
        self.values = ValueStore(base / "values.json")
        self.engine = HttpEngine(self.store, self.history, httpx.MockTransport(self.api), self.requests, self.values)

    def target(self, **fields: Any) -> dict[str, Any]:
        return self.store.create({"baseUrl": ORIGIN, "allowPrivate": True, **fields})

    def saved(self, target_id: str, **fields: Any) -> dict[str, Any]:
        return self.requests.create({"targetId": target_id, **fields})

    def token_target(self, name: str, refresh: str) -> tuple[str, str]:
        """A target whose bearer token is a captured variable, and the saved request that renews it: their ids."""
        bearer = {"type": "bearer", "token": "{{access_token}}"}
        target = self.target(name=name, auth=bearer, secrets={"client_secret": "app-secret-value"})
        saved = self.saved(
            target["id"],
            name="get token",
            method="POST",
            path="/token",
            bodyMode="json",
            body='{"secret":"{{client_secret}}"}',
            # The token request authenticates with the secret, not with the token it obtains.
            headers=[{"key": "Authorization", "value": "Basic x", "enabled": True}],
            captures=[rule("access_token", "access_token", refresh, ttlPath="expires_in")],
        )
        return target["id"], saved["id"]

    async def send(self, ref: str, method: str, path: str, source: str = "agent", **fields: Any) -> dict[str, Any]:
        return await self.engine.send(ref, {"method": method, "path": path, **fields}, SendOptions(source=source))


@pytest.fixture
async def lab(tmp_path: Path) -> Any:
    lab = Lab(tmp_path)
    yield lab
    await lab.engine.aclose()


def rule(name: str, path: str, refresh: str = "off", **fields: Any) -> dict[str, Any]:
    return {**blank_capture(), "name": name, "path": path, "refresh": refresh, **fields}


def outcomes(exchange: dict[str, Any], *fields: str) -> list[tuple[Any, ...]]:
    """The named fields of each refresh an exchange lists."""
    return [tuple(item.get(field) for field in fields) for item in exchange.get("refreshed", [])]


def test_variable_helpers():
    assert referenced_variables(["/x/{{ a }}?b={{b}}", "Bearer {{a}}", "{{ not valid }}"]) == {"a", "b"}
    form = {
        "method": "POST",
        "path": "/p",
        "query": [
            {"key": "q", "value": "1"},
            {"key": "off", "value": "2", "enabled": False},
            {"key": " ", "value": "x"},
        ],
        "headers": [{"key": "X-A", "value": "a"}],
        "auth": {"type": "none"},
        "bodyMode": "form",
        "body": "ignored",
        "form": [{"key": "f", "value": "v w"}, {"key": "g", "value": "~*é"}],
    }
    assert request_input_of(form) == {
        "method": "POST",
        "path": "/p",
        "query": [["q", "1"]],
        "headers": {"X-A": "a", "content-type": "application/x-www-form-urlencoded; charset=utf-8"},
        "body": "f=v+w&g=%7E*%C3%A9",
    }
    bearer = {"type": "bearer", "token": "t"}
    sent = request_input_of({**form, "method": "GET", "auth": bearer, "bodyMode": "json", "body": "{}"})
    assert sent["body"] is None and sent["auth"] == bearer and "content-type" not in sent["headers"]
    typed = request_input_of({**form, "bodyMode": "json", "body": "{}"})
    assert typed["body"] == "{}" and typed["headers"]["content-type"] == "application/json; charset=utf-8"
    # A value counts as expired 30 s before its expiry, or a tenth of its lifetime early when that is shorter.
    now = 1_000_000
    assert not is_expired({"at": now}, now)
    assert not is_expired({"at": now - 7_200_000 + 31_000, "expiresAt": now + 31_000}, now)
    assert is_expired({"at": now - 7_200_000 + 29_000, "expiresAt": now + 29_000}, now)
    assert not is_expired({"at": now - 800, "expiresAt": now + 200}, now)
    assert is_expired({"at": now - 950, "expiresAt": now + 50}, now)


def test_capture_rules():
    assert parse_json_path("data.token") == ["data", "token"]
    assert parse_json_path("$.items[0].id") == ["items", 0, "id"]
    assert parse_json_path("$[\"a.b\"]['c d']") == ["a.b", "c d"] and parse_json_path("[2]") == [2]
    for bad in ("", "$", "a..b", "a[", "a[x]", "$a", "a" * 513):
        rejects(lambda bad=bad: parse_json_path(bad), ".", ValueError)
    root = {"data": {"token": "t", "list": [{"id": 7}]}}
    assert read_path(root, ["data", "token"]) == "t" and read_path(root, ["data", "list", 0, "id"]) == 7
    assert read_path(root, ["data", "list", "0", "id"]) == 7 and read_path(root, ["data", "list", 3, "id"]) is None
    assert read_path(root, ["data", "token", "length"]) is None and read_path(root, ["data", "items"]) is None
    headers = httpx.Headers({"x-session": "sess-1", "content-type": "application/json"})
    data = {"access_token": "tok-123", "expires": 3600, "ratio": 1.5, "whole": 2.0, "on": True, "nested": {"a": 1}}
    body = json.dumps({"data": {**data, "empty": "", "none": None, "lines": "a\nb", "long": "x" * 16385}})
    rules = [
        rule("token", "data.access_token"),
        rule("ttl", "$.data.expires"),
        rule("ratio", "data.ratio"),
        rule("whole", "data.whole"),
        rule("on", "data.on"),
        rule("session", "X-Session", source="header"),
        rule("off", "data.access_token", enabled=False),
        rule("", "data.access_token"),
        rule("missing", "data.nope"),
        rule("null", "data.none"),
        rule("object", "data.nested"),
        rule("blank", "data.empty"),
        rule("lines", "data.lines"),
        rule("long", "data.long"),
        rule("bad name", "data.access_token"),
        rule("badpath", "data..x"),
        rule("nohdr", "x-none", source="header"),
        rule("badhdr", "x none", source="header"),
        rule("emptyhdr", " ", source="header"),
    ]
    values, lifetimes, results = run_captures(rules, 200, headers, body, False)
    assert values == {
        "token": "tok-123",
        "ttl": "3600",
        "ratio": "1.5",
        "whole": "2",
        "on": "true",
        "session": "sess-1",
    }
    assert lifetimes == {} and [r["name"] for r in results if r["ok"]] == list(values)
    assert {r["name"]: r["error"] for r in results if not r["ok"]} == {
        "missing": 'path "data.nope" not found',
        "null": 'path "data.none" not found',
        "object": "value is not a string, number or boolean",
        "blank": "value is empty",
        "lines": "value contains line breaks",
        "long": "value is too long",
        "bad name": "invalid variable name",
        "badpath": "name expected at 5",
        "nohdr": 'header "x-none" not found',
        "badhdr": 'invalid header name "x none"',
        "emptyhdr": "header name is empty",
    }
    # Each reason a response gives nothing: its status, a body that is not JSON, a body cut short.
    one = [rule("token", "data.access_token")]
    for status, text, cut, reason in (
        (401, body, False, "response status 401"),
        (200, "plain", False, "response body is not JSON"),
        (200, "NaN", False, "response body is not JSON"),
        (200, body, True, "response body is truncated"),
    ):
        assert run_captures(one, status, headers, text, cut) == (
            {},
            {},
            [{"name": "token", "ok": False, "error": reason}],
        )
    # A header rule needs no JSON body.
    assert run_captures([rule("session", "x-session", source="header")], 204, headers, "", False)[0] == {
        "session": "sess-1"
    }
    # A lifetime comes from the response path, else from the fixed seconds; an unreadable path warns.
    body = json.dumps(
        {"access_token": "tok-123", "expires_in": 7200, "text": " 90 ", "bad": "soon", "zero": 0, "on": True}
    )
    timed = [
        rule("fixed", "access_token", ttlSeconds=600),
        rule("fromPath", "access_token", ttlSeconds=600, ttlPath="expires_in"),
        rule("numericText", "access_token", ttlPath="$.text"),
        rule("unreadable", "access_token", ttlPath="bad"),
        rule("absent", "access_token", ttlPath="nope"),
        rule("zero", "access_token", ttlPath="zero"),
        rule("flag", "access_token", ttlPath="on"),
        rule("malformed", "access_token", ttlPath="a..b"),
        rule("forever", "access_token"),
        rule("sid", "x-session", source="header", ttlPath="expires_in"),
    ]
    values, lifetimes, results = run_captures(timed, 200, headers, body, False)
    assert lifetimes == {"fixed": 600_000, "fromPath": 7_200_000, "numericText": 90_000, "sid": 7_200_000}
    assert list(values) == [r["name"] for r in results] and all(r["ok"] for r in results)
    assert [r["name"] for r in results if "warning" in r] == ["unreadable", "absent", "zero", "flag", "malformed"]
    assert results[3]["warning"] == 'lifetime "bad" is not a positive number of seconds'


def test_capture_rules_and_values_in_the_stores(tmp_path):
    requests = RequestStore(tmp_path / "requests.json")
    saved = requests.create(
        {
            "targetId": "x",
            "path": "/",
            "captures": [
                {"name": "a", "source": "body", "path": "p", "enabled": True},
                rule("b", "p", "sometimes", ttlSeconds=10**12, source="cookie"),
                rule("c", "p", "rejected", ttlSeconds=-5, ttlPath="data.expires_in", source="header", enabled=False),
                "junk",
            ],
        }
    )
    assert saved["captures"] == [
        rule("a", "p"),
        rule("b", "p", ttlSeconds=366 * 86400),
        rule("c", "p", "rejected", ttlPath="data.expires_in", source="header", enabled=False),
        blank_capture(),
    ]
    assert RequestStore(requests.path).get(saved["id"])["captures"] == saved["captures"]
    for captures, message in (
        ({}, "array of rules"),
        ([rule("a", "p")] * 21, "at most 20 rules"),
        ([rule("a" * 129, "p")], "too long"),
        ([rule("a", "p" * 513)], "too long"),
        ([rule("a", "p\nq")], "line breaks"),
    ):
        rejects(lambda captures=captures: requests.update(saved["id"], {"captures": captures}), message)
    assert requests.update(saved["id"], {"name": "kept"})["captures"] == saved["captures"]
    assert requests.update(saved["id"], {"captures": []})["captures"] == []
    # Values: per scope, secret-free when listed, expiry kept across a reload, mode 0600.
    values = ValueStore(tmp_path / "values.json")
    values.set(
        "t1",
        {"token": "value-number-1", "Forever": "v2", "bad name": "x", "long": "x" * 16385},
        saved["id"],
        {"token": 5000},
    )
    values.set("direct", {"token": "other-scope"}, "")
    assert values.map("t1") == {"token": "value-number-1", "Forever": "v2"} and values.map("none") == {}
    again = ValueStore(values.path)
    entry = again.entry("t1", "token")
    assert entry["expiresAt"] - entry["at"] == 5000 and entry["requestId"] == saved["id"]
    assert "expiresAt" not in again.entry("t1", "Forever") and again.entry("t1", "none") is None
    listed = again.list("t1")
    assert [(v["name"], v["hint"], v.get("expiresAt")) for v in listed] == [
        ("Forever", "••••", None),
        ("token", "val…-1", entry["expiresAt"]),
    ]
    assert "value-number-1" not in json.dumps(listed) and set(listed[1]) == {
        "name",
        "hint",
        "requestId",
        "at",
        "expiresAt",
    }
    assert stat.S_IMODE(values.path.stat().st_mode) == 0o600
    assert (again.delete("t1", "none"), again.delete("t1", "token"), again.delete("none")) == (0, 1, 0)
    assert (
        again.delete("t1") == 1
        and again.list("t1") == []
        and ValueStore(values.path).map("direct") == {"token": "other-scope"}
    )
    values.path.write_text("{oops")
    assert ValueStore(values.path).map("direct") == {}


async def test_secret_variables(lab):
    store, api = lab.store, lab.api
    target = lab.target(name="secrets", variables={"org": "acme"}, secrets={"client_secret": "app-secret-value"})
    assert summarize(target)["secrets"] == {"client_secret": "app…ue"}
    assert "app-secret-value" not in json.dumps(summarize(target)) and "app-secret-value" in store.path.read_text()
    tid = target["id"]
    rejects(lambda: store.update(tid, {"variables": {"client_secret": "x"}}), "both a variable and a secret variable")
    rejects(
        lambda: store.create({"baseUrl": ORIGIN, "variables": {"k": "v"}, "secrets": {"k": "s"}}), "both a variable"
    )
    rejects(lambda: store.update(tid, {"secrets": {"client_secret": "", "other": ""}}), '"other" is required')
    rejects(lambda: store.create({"baseUrl": ORIGIN, "secrets": {"1bad": "x"}}), "invalid name")
    rejects(lambda: store.create({"baseUrl": ORIGIN, "secrets": {"k": "a\nb"}}), "line breaks")
    # An empty value keeps the stored one; a name left out is removed; other fields leave the secrets alone.
    kept = {"client_secret": "app-secret-value"}
    assert store.update(tid, {"secrets": {"client_secret": "", "extra": "second-secret"}})["secrets"] == {
        **kept,
        "extra": "second-secret",
    }
    assert store.update(tid, {"secrets": {"client_secret": ""}})["secrets"] == kept
    assert store.update(tid, {"name": "secrets"})["secrets"] == kept
    # Substituted like a variable; masked in the URL, the headers, the echoed response, the errors and the history.
    typed = {
        "method": "POST",
        "path": "/echo",
        "query": {"k": "{{client_secret}}"},
        "headers": {"X-Secret": "{{client_secret}}"},
    }
    sent = await lab.send("secrets", **typed, body='{"secret":"{{client_secret}}","org":"{{org}}"}')
    assert api.seen[-1][0] == "/echo?k=app-secret-value" and api.seen_at("/echo")["x-secret"] == "app-secret-value"
    assert "app-secret-value" not in json.dumps(sent) and '"x-secret":"••••••"' in sent["response"]["body"]
    assert (
        sent["request"]["url"] == f"{ORIGIN}/echo?k=••••••" and sent["request"]["sentHeaders"]["x-secret"] == "••••••"
    )
    assert sent["request"]["body"] == '{"secret":"{{client_secret}}","org":"{{org}}"}'
    assert sent["request"]["headers"] == {"X-Secret": "{{client_secret}}"}
    await lab.send("secrets", "POST", "/token", body='{"secret":"{{client_secret}}","org":"{{org}}"}')
    assert api.token_bodies == ['{"secret":"app-secret-value","org":"acme"}']
    refused = await lab.send("secrets", "GET", "https://{{client_secret}}.test/")
    assert refused["error"].startswith("host '••••••.test' is not allowed") and "app-secret-value" not in json.dumps(
        refused
    )
    assert "app-secret-value" not in lab.history.path.read_text()
    listed = await build_tools(lab)[0].ainvoke({})
    assert "| {{org}} {{client_secret}} |" in listed and "app-secret-value" not in listed
    # A secret variable without a stored value stops the requests that reference it, and only those.
    file = json.loads(store.path.read_text())
    file["targets"][0]["secrets"] = {"client_secret": "", "unused": ""}
    store.path.write_text(json.dumps(file))
    assert summarize(store.find("secrets"))["secrets"] == {"client_secret": "", "unused": ""}
    calls = api.token_calls
    refused = await lab.send("secrets", "POST", "/token", "panel", body="{{client_secret}}")
    assert "response" not in refused and api.token_calls == calls and refused["request"]["url"] == ""
    assert refused["error"] == (
        "secret variable {{client_secret}} of target 'secrets' is not filled in (edit the target on the HTTP page)"
    )
    assert "error" not in await lab.send("secrets", "POST", "/token", "panel", body="{}")
    rejects(lambda: store.update(tid, {"secrets": {"client_secret": ""}}), '"client_secret" is required')
    assert store.update(tid, {"secrets": {"client_secret": "filled-in-again"}})["secrets"] == {
        "client_secret": "filled-in-again"
    }
    assert "error" not in await lab.send("secrets", "POST", "/token", "panel", body="{{client_secret}}")


async def test_variables_in_fixed_headers_and_auth(lab):
    api = lab.api
    target = lab.target(
        name="fixed",
        variables={"region": "eu"},
        secrets={"api_key": "key-secret-123"},
        headers={"X-Region": "{{region}}", "X-Key": "{{api_key}}", "X-Sid": "sid {{sid}}", "X-Unknown": "{{nope}}"},
        auth={"type": "query", "name": "k", "value": "{{api_key}}"},
    )
    # An auth value that is exactly one reference is shown as written; any other value as a hint.
    assert summarize(target)["auth"] == {"type": "query", "name": "k", "hint": "{{api_key}}"}
    mixed = {"type": "header", "name": "X-Token", "value": "T-{{region}}-{{api_key}}"}
    assert summarize({**target, "auth": mixed})["auth"]["hint"] == "T-{…}}"
    assert (
        summarize({**target, "auth": {"type": "bearer", "token": " {{ api_key }} "}})["auth"]["hint"] == "{{ api_key }}"
    )
    lab.saved(target["id"], name="get sid", path="/a", captures=[rule("sid", "value", "expired")])
    sent = await lab.send("fixed", "GET", "/echo")
    assert sent["response"]["status"] == 200
    assert outcomes(sent, "requestName", "variables", "ok") == [("get sid", ["sid"], True)]
    # The server received the values; an undefined name stays as written.
    got = api.seen_at("/echo")
    assert (got["x-region"], got["x-key"], got["x-sid"], got["x-unknown"]) == (
        "eu",
        "key-secret-123",
        "sid a-value-1",
        "{{nope}}",
    )
    assert api.seen[-1][0] == "/echo?k=key-secret-123"
    # The exchange shows the secret and the captured value masked, the plain variable as it is.
    wire = sent["request"]["sentHeaders"]
    assert "key-secret-123" not in json.dumps(sent) and "a-value-1" not in json.dumps(sent)
    assert (wire["x-region"], wire["x-sid"], sent["request"]["url"]) == ("eu", "sid ••••••", f"{ORIGIN}/echo?k=••••••")
    # The request that obtains {{sid}} is sent without the fixed header that carries it, and with the others.
    refresh = api.seen_at("/a")
    assert "x-sid" not in refresh and (refresh["x-region"], refresh["x-key"]) == ("eu", "key-secret-123")
    # Header and basic auth take variables too.
    lab.store.update(target["id"], {"auth": mixed})
    header = await lab.send("fixed", "GET", "/echo")
    assert api.seen_at("/echo")["x-token"] == "T-eu-key-secret-123" and "key-secret-123" not in json.dumps(header)
    lab.store.update(target["id"], {"auth": {"type": "basic", "username": "svc-{{region}}", "password": "{{api_key}}"}})
    basic = await lab.send("fixed", "GET", "/echo")
    pair = base64.b64encode(b"svc-eu:key-secret-123").decode()
    assert api.seen_at("/echo")["authorization"] == f"Basic {pair}"
    assert "key-secret-123" not in json.dumps(basic) and pair not in json.dumps(basic)
    # A request's own auth takes variables as well, when the page sends it to a target without auth.
    bare = lab.target(name="bare", secrets={"api_key": "key-secret-456"})
    own = await lab.send(bare["id"], "GET", "/echo", "panel", auth={"type": "bearer", "token": "{{api_key}}"})
    assert api.seen_at("/echo")["authorization"] == "Bearer key-secret-456" and "key-secret-456" not in json.dumps(own)


async def test_captured_variables(lab):
    api, values = lab.api, lab.values
    target = lab.target(name="chain", variables={"token": "static-value"}, secrets={"session": "secret-session"})
    tid = target["id"]
    captures = [
        rule("token", "data.access_token"),
        rule("session", "x-session", source="header"),
        rule("gone", "data.nope"),
    ]
    login = lab.saved(tid, method="POST", path="/login", captures=captures)
    first = await lab.send(tid, "POST", "/login", "panel", requestId=login["id"])
    assert first["captures"] == [
        {"name": "token", "ok": True},
        {"name": "session", "ok": True},
        {"name": "gone", "ok": False, "error": 'path "data.nope" not found'},
    ]
    # The captured values are masked in the response they came from, and kept in the fourth store.
    assert (
        first["response"]["body"] == '{"data":{"access_token":"••••••"}}'
        and first["response"]["headers"]["x-session"] == "••••••"
    )
    assert "secret-token-1" not in json.dumps(first) and "sess-1" not in json.dumps(first)
    assert values.map(tid) == {"token": "secret-token-1", "session": "sess-1"}
    assert [(v["name"], v["hint"], v["requestId"]) for v in values.list(tid)] == [
        ("session", "••••", login["id"]),
        ("token", "sec…-1", login["id"]),
    ]
    assert first["at"] <= values.entry(tid, "token")["at"] and "expiresAt" not in values.entry(tid, "token")
    assert stat.S_IMODE(values.path.stat().st_mode) == 0o600
    # A captured value wins over the target variable and the secret variable of its name; the agent's requests use it.
    typed = {"Authorization": "Bearer {{token}}", "X-Session": "{{session}}"}
    me = await lab.send("chain", "GET", "/echo", query={"s": "{{session}}"}, headers=typed)
    got = api.seen_at("/echo")
    assert (got["authorization"], got["x-session"], api.seen[-1][0]) == (
        "Bearer secret-token-1",
        "sess-1",
        "/echo?s=sess-1",
    )
    assert "captures" not in me and '"authorization":"Bearer ••••••"' in me["response"]["body"]
    assert "secret-token-1" not in json.dumps(me) and "sess-1" not in json.dumps(me)
    assert me["request"]["headers"] == typed and me["request"]["url"] == f"{ORIGIN}/echo?s=••••••"
    assert "secret-token-1" not in lab.history.path.read_text() and "sess-1" not in lab.history.path.read_text()
    assert "| {{token}} {{session}} |" in await build_tools(lab)[0].ainvoke({})
    # Sending the source request again renews the value.
    await lab.send(tid, "POST", "/login", "panel", requestId=login["id"])
    assert values.map(tid) == {"token": "secret-token-2", "session": "sess-2"}
    # Not captured: each reason is reported and the stored values stay.
    one = [rule("token", "data.access_token")]
    cut = SendOptions(source="panel", max_body_bytes=10)
    for path, options, reason in (
        ("/denied", PANEL, "response status 403"),
        ("/plain", PANEL, "response body is not JSON"),
        ("/login", cut, "response body is truncated"),
        ("/stream", PANEL, "event streams are not captured"),
    ):
        saved = lab.saved(tid, path=path, captures=[*one, rule("off", "data.access_token", enabled=False)])
        missed = await lab.engine.send(tid, {"method": "GET", "path": path, "requestId": saved["id"]}, options)
        assert "error" not in missed and missed["captures"] == [{"name": "token", "ok": False, "error": reason}]
        assert lab.history.list(tid)[0]["captures"] == missed["captures"]
    assert values.map(tid) == {"token": "secret-token-2", "session": "sess-2"}
    # No rules run for the agent's own send, a request of another scope, or a send without its saved request.
    other = lab.target(name="other")
    await lab.send("chain", "POST", "/login", requestId=login["id"])
    assert "captures" not in await lab.send(other["id"], "POST", "/login", "panel", requestId=login["id"])
    assert "captures" not in await lab.send(tid, "POST", "/login", "panel")
    assert values.map(tid)["token"] == "secret-token-2" and values.map(other["id"]) == {}
    # Requests without a target capture and substitute within their own scope.
    loose = lab.saved("direct", path=f"{ORIGIN}/login", captures=[rule("direct_token", "data.access_token")])
    assert (await lab.send("direct", "GET", f"{ORIGIN}/login", "panel", requestId=loose["id"]))["captures"] == [
        {"name": "direct_token", "ok": True}
    ]
    typed = {"X-Session": "{{direct_token}}"}
    assert (
        '"x-session":"••••••"'
        in (await lab.send("direct", "GET", f"{ORIGIN}/echo", "panel", headers=typed))["response"]["body"]
    )
    assert values.delete("direct", "direct_token") == 1
    assert (
        "{{direct_token}}"
        in (await lab.send("direct", "GET", f"{ORIGIN}/echo", "panel", headers=typed))["response"]["body"]
    )


async def test_refresh_before_a_request(lab):
    api, values, history = lab.api, lab.values, lab.history
    tid, token_request = lab.token_target("auto", "expired")
    first = await lab.send("auto", "GET", "/orders")
    assert first["response"]["status"] == 200 and api.token_calls == 1
    assert api.token_bodies == ['{"secret":"app-secret-value"}']
    assert outcomes(first, "requestId", "requestName", "variables", "reason", "ok") == [
        (token_request, "get token", ["access_token"], "missing", True)
    ]
    # Neither the token nor the secret reaches the agent or the history.
    assert "access-token-1" not in json.dumps(first) and "app-secret-value" not in json.dumps(first)
    assert "access-token-" not in history.path.read_text() and "app-secret-value" not in history.path.read_text()
    assert first["request"]["sentHeaders"]["authorization"] == "Bearer ••••••"
    # The refresh is its own history entry, attributed to the sender that caused it.
    recorded = history.list(tid)
    assert [(e["request"]["path"], e["source"], e.get("refreshOf")) for e in recorded] == [
        ("/orders", "agent", None),
        ("/token", "agent", ["access_token"]),
    ]
    assert recorded[1]["id"] == first["refreshed"][0]["exchangeId"] and recorded[1]["requestId"] == token_request
    assert recorded[1]["captures"] == [{"name": "access_token", "ok": True}] and "refreshed" not in recorded[1]
    # The token request is sent as stored, with its own header, without the target auth that carries the token.
    assert recorded[1]["request"]["sentHeaders"]["authorization"] == "Basic x"
    assert recorded[1]["request"]["sentHeaders"]["content-type"] == "application/json; charset=utf-8"
    # The value carries the lifetime the response states, and is used as it is while it lasts.
    entry = values.entry(tid, "access_token")
    assert entry["value"] == "access-token-1" and entry["expiresAt"] - entry["at"] == 7_200_000
    assert values.list(tid)[0]["expiresAt"] == entry["expiresAt"]
    second = await lab.send("auto", "GET", "/orders")
    assert second["response"]["status"] == 200 and "refreshed" not in second and api.token_calls == 1
    # An expired value is renewed.
    api.valid.add("old-token")
    values.set(tid, {"access_token": "old-token"}, token_request, {"access_token": 20})
    await asyncio.sleep(0.03)
    renewed = await lab.send(tid, "GET", "/orders", "panel")
    assert outcomes(renewed, "reason", "ok") == [("expired", True)] and '"ok":true' in renewed["response"]["body"]
    assert values.entry(tid, "access_token")["value"] == "access-token-2"
    # With the rule off an expired value is sent as it is, and a missing one is not obtained.
    off, off_request = lab.token_target("expiry-off", "off")
    values.set(off, {"access_token": "old-token"}, off_request, {"access_token": 1})
    await asyncio.sleep(0.005)
    calls = api.token_calls
    stale = await lab.send(off, "GET", "/orders", "panel")
    assert stale["response"]["status"] == 200 and "refreshed" not in stale
    values.delete(off)
    assert (await lab.send(off, "GET", "/orders", "panel"))["response"]["status"] == 401 and api.token_calls == calls
    # A rule switched off refreshes nothing either.
    lab.requests.update(token_request, {"captures": [rule("access_token", "access_token", "expired", enabled=False)]})
    values.delete(tid)
    assert "refreshed" not in await lab.send(tid, "GET", "/orders", "panel") and api.token_calls == calls
    lab.requests.update(token_request, {"captures": [rule("access_token", "access_token", "expired")]})
    # Sending the token request itself runs no refresh first.
    form = {**request_input_of(lab.requests.get(token_request)), "requestId": token_request}
    own = await lab.engine.send(tid, form, PANEL)
    assert (
        "refreshed" not in own and "refreshOf" not in own and own["captures"] == [{"name": "access_token", "ok": True}]
    )
    assert "expiresAt" not in values.entry(tid, "access_token")
    # The connection test of a target whose token is a variable obtains the token first.
    values.delete(tid)
    calls = api.token_calls
    tested = await lab.engine.test(tid)
    assert (tested["ok"], tested["status"], api.token_calls) == (True, 200, calls + 1)


async def test_refresh_shared_failed_and_cancelled(lab):
    api, values, history = lab.api, lab.values, lab.history
    # Concurrent requests share one refresh.
    api.token_delay = 0.06
    tid, _token_request = lab.token_target("shared", "expired")
    results = await asyncio.gather(
        *(lab.send(tid, "GET", f"/orders/{n}", "agent" if n % 2 == 0 else "panel") for n in range(1, 6))
    )
    assert [r["response"]["status"] for r in results] == [200] * 5 and api.token_calls == 1
    assert len({r["refreshed"][0]["exchangeId"] for r in results}) == 1
    assert sum("refreshOf" in e for e in history.list(tid)) == 1
    # A failed refresh stops the request; the error names the source request and the reason.
    api.token_delay, api.token_status = 0.0, 500
    failing, _token_request = lab.token_target("failing", "expired")
    calls, sent = api.token_calls, api.api_calls
    failed = await lab.send(failing, "DELETE", "/orders/1")
    assert "response" not in failed and failed["error"] == (
        "refresh of {{access_token}} by request 'get token' failed: {{access_token}} was not captured: response "
        "status 500"
    )
    assert outcomes(failed, "ok", "reason") == [(False, "missing")]
    assert (api.api_calls, api.token_calls) == (sent, calls + 1) and history.list(failing)[0]["error"] == failed[
        "error"
    ]
    output = to_output(failed)
    assert output["ok"] is False and output["refreshed"][0]["ok"] is False
    assert render_exchange("DELETE", output).startswith("request failed: refresh of {{access_token}} by request")
    # Nothing is retried within one request; the next request tries again.
    await lab.send(failing, "GET", "/orders")
    assert api.token_calls == calls + 2
    # A refresh whose saved request cannot be sent is a failed refresh.
    broken = lab.target(name="broken")
    lab.saved(
        broken["id"],
        name="bad",
        path="/a",
        headers=[{"key": "X-A", "value": "a\nb"}],
        captures=[rule("v", "value", "expired")],
    )
    assert (
        "by request 'bad' failed: header X-A must not contain line breaks"
        in (await lab.send(broken["id"], "GET", "/echo", headers={"X-V": "{{v}}"}))["error"]
    )
    # Cancelling stops the wait; the refresh under way completes and its value is kept.
    api.token_status, api.token_delay = 200, 0.3
    cancel = asyncio.Event()
    loop = asyncio.get_running_loop()
    loop.call_later(0.03, cancel.set)
    started = loop.time()
    options = SendOptions(source="panel", cancel=cancel)
    cancelled = await lab.engine.send(failing, {"method": "GET", "path": "/orders"}, options)
    assert cancelled["error"] == "cancelled" and loop.time() - started < 0.25 and api.api_calls == sent
    assert outcomes(cancelled, "ok", "error") == [(False, "cancelled")]
    await asyncio.sleep(0.35)
    assert values.entry(failing, "access_token")["value"].startswith("access-token-")


async def test_refresh_on_401(lab):
    api, values, history = lab.api, lab.values, lab.history
    tid, token_request = lab.token_target("rejected", "rejected")
    values.set(tid, {"access_token": "revoked-token"}, token_request, {"access_token": 7_200_000})
    retried = await lab.send(tid, "GET", "/orders")
    assert retried["response"]["status"] == 200 and outcomes(retried, "reason", "ok") == [("rejected", True)]
    assert (api.api_calls, api.token_calls) == (2, 1)
    # The rejected attempt, the refresh and the second attempt are three entries.
    assert [(e["request"]["path"], e["response"]["status"]) for e in history.list(tid)] == [
        ("/orders", 200),
        ("/token", 200),
        ("/orders", 401),
    ]
    assert "refreshed" not in history.list(tid)[2] and "revoked-token" not in history.path.read_text()
    # A 401 that follows a refresh made for this request is returned as it is.
    values.delete(tid)
    denied = await lab.send(tid, "GET", "/always-401")
    assert denied["response"]["status"] == 401 and outcomes(denied, "reason") == [("missing",)]
    assert (api.api_calls, api.token_calls) == (3, 2)
    # A refresh that fails after a 401 leaves the 401 as the result, with the failure listed.
    api.token_status = 500
    kept = await lab.send(tid, "GET", "/always-401")
    assert kept["response"]["status"] == 401 and outcomes(kept, "reason", "ok") == [("rejected", False)]
    assert api.api_calls == 4
    api.token_status = 200
    # A 401 that is an event stream is returned as it is.
    calls = api.token_calls
    stream = await lab.send(tid, "GET", "/sse-401", "panel")
    assert stream["response"]["status"] == 401 and "refreshed" not in stream and api.token_calls == calls
    # A rule that renews on expiry only returns the 401 as it is.
    plain, plain_request = lab.token_target("rejected-plain", "expired")
    values.set(plain, {"access_token": "revoked-token"}, plain_request, {"access_token": 7_200_000})
    unauthorized = await lab.send(plain, "GET", "/orders")
    assert unauthorized["response"]["status"] == 401 and "refreshed" not in unauthorized and api.token_calls == calls


async def test_refresh_chains_and_sources(lab):
    api, values = lab.api, lab.values
    expired = lambda name, path="value": [rule(name, path, "expired")]  # noqa: E731
    # b is obtained with a; a is obtained with nothing.
    chain = lab.target(name="chain")["id"]
    lab.saved(chain, name="get a", path="/a", captures=expired("a"))
    lab.saved(chain, name="get b", path="/b", query=[{"key": "with", "value": "{{a}}"}], captures=expired("b"))
    api.valid.add("b-value-1")
    ok = await lab.send(chain, "GET", "/orders", query={"access_token": "{{b}}"})
    assert ok["response"]["status"] == 200 and values.map(chain) == {"a": "a-value-1", "b": "b-value-1"}
    nested = next(e for e in lab.history.list(chain) if e["request"]["path"] == "/b")
    assert outcomes(nested, "requestName", "ok") == [("get a", True)] and nested["refreshOf"] == ["b"]
    assert nested["request"]["url"] == f"{ORIGIN}/b?with=••••••"
    # a needs b and b needs a.
    cycle = lab.target(name="cycle")["id"]
    lab.saved(cycle, name="get a", path="/a", headers=[{"key": "X-B", "value": "{{b}}"}], captures=expired("a"))
    lab.saved(cycle, name="get b", path="/b", headers=[{"key": "X-A", "value": "{{a}}"}], captures=expired("b"))
    looped = await lab.send(cycle, "GET", "/orders", headers={"X-A": "{{a}}"})
    assert "response" not in looped and looped["error"].endswith("the request depends on a variable it refreshes")
    assert values.map(cycle) == {}
    # v0 ← v1 ← v2 ← v3 ← v4: a chain holds three refreshes.
    deep = lab.target(name="deep")["id"]
    for i in range(4):
        needs = [{"key": "with", "value": f"{{{{v{i + 1}}}}}"}]
        lab.saved(deep, name=f"get v{i}", path="/a", query=needs, captures=expired(f"v{i}"))
    lab.saved(deep, name="get v4", path="/a", captures=expired("v4"))
    too_deep = await lab.send(deep, "GET", "/orders", headers={"X-V": "{{v1}}"})
    assert too_deep["error"].endswith("more than 3 refreshes in a chain") and values.map(deep) == {}
    fits = await lab.send(deep, "GET", "/orders", headers={"X-V": "{{v2}}"})
    assert "error" not in fits and sorted(values.map(deep)) == ["v2", "v3", "v4"]
    # One request provides several variables in one send.
    sources = lab.target(name="sources")["id"]
    pair = [rule("first", "first", "expired"), rule("second", "second", "expired"), rule("unused", "first", "expired")]
    lab.saved(sources, name="pair", path="/pair", captures=pair)
    both = await lab.send(sources, "GET", "/echo", headers={"X-One": "{{first}}", "X-Two": "{{second}}"})
    assert api.pair_calls == 1 and outcomes(both, "variables", "ok") == [(["first", "second"], True)]
    assert (api.seen_at("/echo")["x-one"], api.seen_at("/echo")["x-two"]) == ("pair-first-value", "pair-second-value")
    # Of several sources of a variable: the request its value came from; without a value, the one created first.
    from_a = lab.saved(sources, name="from a", path="/a", captures=expired("shared"))
    from_b = lab.saved(sources, name="from b", path="/b", captures=expired("shared"))
    typed = {"X-S": "{{shared}}"}
    assert outcomes(await lab.send(sources, "GET", "/echo", headers=typed), "requestId") == [(from_a["id"],)]
    assert values.entry(sources, "shared")["value"] == "a-value-1"
    values.set(sources, {"shared": "stale"}, from_b["id"], {"shared": 1})
    await asyncio.sleep(0.005)
    second = await lab.send(sources, "GET", "/echo", headers=typed)
    assert outcomes(second, "requestId", "reason") == [(from_b["id"], "expired")]
    assert values.entry(sources, "shared")["value"] == "b-value-1"
    # A rule switched off, and a rule whose request is gone, refresh nothing.
    lab.requests.update(from_a["id"], {"captures": [rule("shared", "value", "expired", enabled=False)]})
    lab.requests.delete(from_b["id"])
    values.delete(sources, "shared")
    assert "refreshed" not in await lab.send(sources, "GET", "/echo", headers=typed)
    assert api.seen_at("/echo")["x-s"] == "{{shared}}"
    # Requests without a target refresh within their own scope; a rule of another scope does not refresh here.
    token = [rule("direct_token", "access_token", "expired", ttlSeconds=600)]
    loose = lab.saved(
        "direct", name="direct token", method="POST", path=f"{ORIGIN}/token", bodyMode="json", body="{}", captures=token
    )
    typed = {"Authorization": "Bearer {{direct_token}}"}
    sent = await lab.send("direct", "GET", f"{ORIGIN}/orders", "panel", headers=typed)
    assert sent["response"]["status"] == 200 and outcomes(sent, "requestId", "reason", "ok") == [
        (loose["id"], "missing", True)
    ]
    entry = values.entry("direct", "direct_token")
    assert entry["expiresAt"] - entry["at"] == 600_000 and "access-token-1" not in json.dumps(sent)
    calls = api.token_calls
    elsewhere = await lab.send(lab.target(name="elsewhere")["id"], "GET", "/orders", "panel", headers=typed)
    assert elsewhere["response"]["status"] == 401 and "refreshed" not in elsewhere and api.token_calls == calls


async def test_refresh_from_the_agent_tools(lab):
    api, values = lab.api, lab.values
    tid, _token_request = lab.token_target("via-tool", "rejected")
    assert lab.store.find("via-tool")["allowMutations"] is False
    tools = {t.name: t for t in build_tools(lab)}
    # A variable the harness refreshes is listed before it has a value.
    listed = await tools["http_targets"].ainvoke({})
    assert (
        f"via-tool | {ORIGIN} | bearer | GET/HEAD/OPTIONS only | {{{{client_secret}}}} {{{{access_token}}}} | -"
        in listed
    )
    assert values.entry(tid, "access_token") is None
    # The refresh is a POST of the user's saved form: the agent's GET needs neither the mutation switch nor confirm.
    got = await tools["http_request"].ainvoke({"target": "via-tool", "method": "GET", "path": "/orders"})
    lines = got.splitlines()
    assert lines[0].startswith(f"GET {ORIGIN}/orders → 200 OK") and api.token_calls == 1
    assert lines[1] == 'harness refreshed {{access_token}} with the saved request "get token" first'
    assert '"got":"••••••"' in got and "access-token-1" not in got and "app-secret-value" not in got
    # The agent's own POST is still refused, and it cannot send the token request itself.
    refused = await tools["http_request"].ainvoke(
        {"target": "via-tool", "method": "POST", "path": "/token", "body": "{}"}
    )
    assert "GET/HEAD/OPTIONS only" in refused and api.token_calls == 1
    # A 401 renews the token for the agent as well.
    values.set(tid, {"access_token": "revoked-token"}, "", {"access_token": 7_200_000})
    again = await tools["http_request"].ainvoke({"target": "via-tool", "method": "GET", "path": "/orders"})
    assert "→ 200 OK" in again and "harness refreshed {{access_token}}" in again and api.token_calls == 2
    # A failed refresh is the failure of the tool call.
    values.delete(tid)
    api.token_status = 500
    failed = await tools["http_request"].ainvoke({"target": "via-tool", "method": "GET", "path": "/orders"})
    assert failed.startswith("request failed: refresh of {{access_token}} by request 'get token' failed: ")
    # A refresh that fails after a 401 is listed with the 401.
    values.set(tid, {"access_token": "revoked-token"}, "", {"access_token": 7_200_000})
    kept = await tools["http_request"].ainvoke({"target": "via-tool", "method": "GET", "path": "/orders"})
    assert (
        "→ 401 Unauthorized" in kept
        and (
            'harness could not refresh {{access_token}} with the saved request "get token": {{access_token}} was not '
            "captured: response status 500"
        )
        in kept
    )
    assert "[agent] via-tool: POST" in await tools["http_history"].ainvoke({"target": "via-tool"})


async def test_stored_data_from_before_these_fields(tmp_path):
    api = Api()
    target_id, request_id = "aaaaaaaaaaaa", "bbbbbbbbbbbb"
    target = {
        "id": target_id,
        "name": "legacy",
        "baseUrl": ORIGIN,
        "auth": {"type": "bearer", "token": "legacy-token-1"},
        "headers": {"X-Fixed": "yes"},
        "variables": {"org": "acme"},
        "allowedHosts": [],
        "allowMutations": False,
        "allowPrivate": True,
        "timeoutMs": 30000,
        "createdAt": 1,
        "updatedAt": 1,
    }
    form = {"query": [], "headers": [], "auth": {"type": "none"}, "bodyMode": "json", "body": "{}", "form": []}
    login = {"id": request_id, "targetId": target_id, "name": "login", "method": "POST", "path": "/token", **form}
    plain = {**login, "id": "cccccccccccc", "name": "plain", "path": "/echo"}
    partial = {**login, "id": "dddddddddddd", "captures": [{"name": "token", "source": "body", "path": "access_token"}]}
    settings = {"agentTools": True, "historyLimit": 200}
    (tmp_path / "targets.json").write_text(json.dumps({"version": 1, "settings": settings, "targets": [target]}))
    (tmp_path / "requests.json").write_text(json.dumps({"version": 1, "requests": [login, plain, partial]}))
    store, requests = TargetStore(tmp_path / "targets.json"), RequestStore(tmp_path / "requests.json")
    values = ValueStore(tmp_path / "values.json")
    history = HistoryStore(tmp_path / "history.jsonl", lambda: 100)
    engine = HttpEngine(store, history, httpx.MockTransport(api), requests, values)
    # A target without secrets and saved requests without capture rules load with the defaults.
    assert store.find("legacy")["secrets"] == {} and summarize(store.find("legacy"))["secrets"] == {}
    assert summarize(store.find("legacy"))["auth"] == {"type": "bearer", "hint": "leg…-1"}
    assert requests.get(request_id)["captures"] == [] and requests.get("cccccccccccc")["captures"] == []
    assert requests.get("dddddddddddd")["captures"] == [rule("token", "access_token")]
    assert values.list(target_id) == [] and not values.path.exists()
    # They behave as before: variables, fixed headers and auth are sent, nothing is captured or refreshed.
    sent = await engine.send(target_id, {"method": "POST", "path": "/echo", "requestId": "cccccccccccc"}, PANEL)
    got = api.seen_at("/echo")
    assert (got["x-fixed"], got["authorization"]) == ("yes", "Bearer legacy-token-1")
    assert not {"captures", "refreshed", "refreshOf"} & set(sent) and "legacy-token-1" not in json.dumps(sent)
    assert "error" not in await engine.send(
        "legacy", {"method": "GET", "path": "/echo/{{org}}"}, SendOptions(source="agent")
    )
    assert api.seen[-1][0] == "/echo/acme" and not values.path.exists()
    # An engine without the request and value stores sends as before.
    bare = HttpEngine(store, history, httpx.MockTransport(api))
    alone = await bare.send(
        target_id, {"method": "GET", "path": "/echo", "headers": {"X-T": "{{token}}"}, "requestId": request_id}, PANEL
    )
    assert alone["response"]["status"] == 200 and "captures" not in alone and api.seen_at("/echo")["x-t"] == "{{token}}"
    # The target takes secret variables and the request a refreshing rule from here on.
    assert store.update(target_id, {"secrets": {"key": "new-secret-value"}})["secrets"] == {"key": "new-secret-value"}
    assert store.find("legacy")["variables"] == {"org": "acme"}
    assert TargetStore(store.path).find("legacy")["auth"] == {"type": "bearer", "token": "legacy-token-1"}
    requests.update(request_id, {"captures": [rule("token", "access_token", "expired")]})
    renewed = await engine.send(
        "legacy", {"method": "GET", "path": "/echo", "headers": {"X-T": "{{token}}"}}, SendOptions(source="agent")
    )
    assert outcomes(renewed, "ok") == [(True,)] and api.seen_at("/echo")["x-t"] == "access-token-1"
    # Values written before lifetimes carry no expiry.
    values.path.write_text(
        json.dumps(
            {
                "version": 1,
                "scopes": {target_id: {"token": {"value": "kept-token-value"}, "1bad": {"value": "x"}, "odd": 5}},
            }
        )
    )
    assert ValueStore(values.path).list(target_id) == [{"name": "token", "hint": "kep…ue", "requestId": "", "at": 0}]
    await engine.aclose()
    await bare.aclose()


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


async def test_variable_routes_in_the_harness(home, tmp_path):
    profile = Profile.init("web", home=str(home))
    patch = [HTTP_OFF, {"id": "http-client", "config": {"data_dir": str(tmp_path / "hc")}, "merge": True}]
    async with Harness(profile, patch=patch) as h:
        service = h.get("httpClient")
        await service.engine.aclose()
        service.engine.client = httpx.AsyncClient(
            transport=httpx.MockTransport(Api()), follow_redirects=False, timeout=None
        )
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=h.get("http").app), base_url="http://t") as c:
            api = "/api/http-client"
            # Targets: secret variables go in as values and come back as hints; an empty value keeps the stored one.
            payload = {
                "baseUrl": ORIGIN,
                "allowPrivate": True,
                "auth": {"type": "bearer", "token": "{{access_token}}"},
                "variables": {"org": "acme"},
                "secrets": {"client_secret": "app-secret-value"},
            }
            created = (await c.post(f"{api}/targets", json=payload)).json()["target"]
            tid = created["id"]
            assert created["secrets"] == {"client_secret": "app…ue"} and created["variables"] == {"org": "acme"}
            assert created["auth"] == {"type": "bearer", "hint": "{{access_token}}"}
            patched = await c.patch(
                f"{api}/targets", params={"id": tid}, json={"secrets": {"client_secret": "", "extra": "second-secret"}}
            )
            assert patched.json()["target"]["secrets"] == {"client_secret": "app…ue", "extra": "sec…et"}
            assert service.store.find(tid)["secrets"]["client_secret"] == "app-secret-value"
            for wrong in ({"secrets": {"org": "x"}}, {"secrets": {"new": ""}}, {"variables": {"extra": "x"}}):
                assert (await c.patch(f"{api}/targets", params={"id": tid}, json=wrong)).status_code == 400
            assert "app-secret-value" not in (await c.get(f"{api}/targets")).text
            # Saved requests: capture rules are stored with every field; a malformed list is refused.
            captures = [{"name": "access_token", "path": "access_token", "ttlPath": "expires_in", "refresh": "expired"}]
            form = {"targetId": tid, "name": "get token", "method": "POST", "path": "/token", "captures": captures}
            saved = (await c.post(f"{api}/requests", json=form)).json()["request"]
            stored = rule("access_token", "access_token", "expired", ttlPath="expires_in")
            assert saved["captures"] == [stored]
            assert (await c.get(f"{api}/requests", params={"target": tid})).json()["requests"][0]["captures"] == [
                stored
            ]
            assert (
                await c.patch(f"{api}/requests", params={"id": saved["id"]}, json={"captures": [stored] * 21})
            ).status_code == 400
            # Values: empty before a capture; an unknown scope is refused.
            assert (await c.get(f"{api}/values", params={"target": tid})).json() == {"values": []}
            assert (await c.get(f"{api}/values", params={"target": "direct"})).json() == {"values": []}
            assert (await c.get(f"{api}/values", params={"target": "ghost"})).status_code == 400
            assert (await c.get(f"{api}/values")).status_code == 400
            assert (await c.delete(f"{api}/values", params={"target": "ghost"})).status_code == 400
            # Send: the refresh runs first; the exchange lists it, the refresh entry is marked.
            sent = (
                await c.post(f"{api}/send", json={"id": tid, "request": {"method": "GET", "path": "/orders/{{org}}"}})
            ).json()["exchange"]
            assert sent["response"]["status"] == 200 and '"path":"/orders/acme"' in sent["response"]["body"]
            assert sent["refreshed"] == [
                {
                    "requestId": saved["id"],
                    "requestName": "get token",
                    "variables": ["access_token"],
                    "reason": "missing",
                    "exchangeId": sent["refreshed"][0]["exchangeId"],
                    "ok": True,
                }
            ]
            entries = (await c.get(f"{api}/history", params={"target": tid})).json()["entries"]
            assert [(e["id"], e.get("refreshOf")) for e in entries] == [
                (sent["id"], None),
                (sent["refreshed"][0]["exchangeId"], ["access_token"]),
            ]
            assert entries[1]["source"] == "panel" and entries[1]["captures"] == [{"name": "access_token", "ok": True}]
            # The page's send of the saved request captures; the value is listed as a hint with its origin.
            own = {"id": tid, "request": {"method": "POST", "path": "/token", "requestId": saved["id"]}}
            captured = (await c.post(f"{api}/send", json=own)).json()["exchange"]
            assert captured["captures"] == [{"name": "access_token", "ok": True}] and "refreshed" not in captured
            assert captured["response"]["body"] == '{"access_token":"••••••","expires_in":7200}'
            listed = (await c.get(f"{api}/values", params={"target": tid})).json()["values"]
            assert len(listed) == 1 and listed[0]["expiresAt"] - listed[0]["at"] == 7_200_000
            assert {k: listed[0][k] for k in ("name", "hint", "requestId")} == {
                "name": "access_token",
                "hint": "acc…-2",
                "requestId": saved["id"],
            }
            # A streamed send carries the same exchange fields.
            ndjson = {"accept": "application/x-ndjson"}
            body = {"id": tid, "request": {"method": "GET", "path": "/stream", "requestId": saved["id"]}}
            lines = [json.loads(x) for x in (await c.post(f"{api}/send", json=body, headers=ndjson)).text.splitlines()]
            assert [line["type"] for line in lines] == ["head", "event", "done"]
            assert lines[-1]["exchange"]["captures"] == [
                {"name": "access_token", "ok": False, "error": "event streams are not captured"}
            ]
            # Clearing one value, then a scope.
            direct = {"targetId": "direct", "path": f"{ORIGIN}/pair", "captures": [{"name": "first", "path": "first"}]}
            loose = (await c.post(f"{api}/requests", json=direct)).json()["request"]
            request = {"method": "GET", "path": f"{ORIGIN}/pair", "requestId": loose["id"]}
            await c.post(f"{api}/send", json={"id": "direct", "request": request})
            assert [
                v["name"] for v in (await c.get(f"{api}/values", params={"target": "direct"})).json()["values"]
            ] == ["first"]
            gone = {"target": tid, "name": "nope"}
            assert (await c.delete(f"{api}/values", params=gone)).json() == {"removed": 0}
            assert (await c.delete(f"{api}/values", params={"target": tid, "name": "access_token"})).json() == {
                "removed": 1
            }
            assert (await c.get(f"{api}/values", params={"target": tid})).json() == {"values": []}
            assert (await c.delete(f"{api}/values", params={"target": "direct"})).json() == {"removed": 1}
            # The tools list the names; deleting a target deletes its captured values.
            await c.post(f"{api}/send", json=own)
            await c.post(f"{api}/settings", json={"agentTools": True})
            tools = {t.name: t for t in h.get("tools").list()}
            assert "| {{org}} {{client_secret}} {{extra}} {{access_token}} |" in await tools["http_targets"].ainvoke({})
            assert "never call a login or token endpoint yourself" in h.get("prompt").render()
            assert service.values.map(tid) != {}
            assert (await c.delete(f"{api}/targets", params={"id": tid})).json() == {"ok": True}
            assert (
                service.values.map(tid) == {}
                and (await c.get(f"{api}/values", params={"target": tid})).status_code == 400
            )
    files = {path.name: stat.S_IMODE(path.stat().st_mode) for path in (tmp_path / "hc").iterdir()}
    assert files == {"targets.json": 0o600, "requests.json": 0o600, "values.json": 0o600, "history.jsonl": 0o600}
