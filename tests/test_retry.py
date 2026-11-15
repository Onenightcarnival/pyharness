"""Model call failures: failure codes, the retry policy, continuing a failed turn, the Gemini protocol."""

from __future__ import annotations

import json

import httpx
import pytest
import yaml

from pyharness import Harness, Profile
from pyharness_llm import CONTINUABLE_CODES, RetryPolicy, failure_code, retry_after_ms
from pyharness_llm.catalog import translate_options
from testkit import scripted
from testkit.scripted import ScriptedError


@pytest.fixture
def profile(home):
    return Profile.init("web", home=str(home))


def patch(replies, llm=None):
    return [
        {"id": "scripted", "name": "testkit.scripted", "after": "llm", "config": {"replies": replies}},
        {"id": "llm", "config": {"default": "scripted:test", **(llm or {})}},
        {"id": "http", "config": {"serve": False}},
    ]


def client(h):
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=h.get("http").app), base_url="http://t", timeout=120)


def sse(text):
    return [json.loads(line[6:]) for line in text.splitlines() if line.startswith("data: ")]


def text_of(events):
    return "".join(e["text"] for e in events if e["type"] == "token")


FAST = {"max_retries": 2, "initial_delay_ms": 0}


# ---------------------------------------------------------------------- units
def test_failure_codes():
    assert failure_code(ScriptedError(code="QUOTA_EXCEEDED")) == "QUOTA_EXCEEDED"  # a provider's own code wins
    for status, code in ((401, "AUTH"), (403, "AUTH"), (429, "RATE_LIMIT"), (408, "TIMEOUT"), (504, "TIMEOUT")):
        assert failure_code(ScriptedError(status_code=status)) == code
    assert failure_code(ScriptedError(status_code=503)) == "SERVER"
    assert failure_code(ScriptedError(status_code=404)) == "HTTP_404"
    assert failure_code(ScriptedError("maximum context length is 8192 tokens", status_code=400)) == (
        "CONTEXT_WINDOW_EXCEEDED"
    )
    assert failure_code(ScriptedError("bad request", status_code=400)) == "HTTP_400"

    response = httpx.Response(429, headers={"retry-after": "3"}, request=httpx.Request("POST", "http://t"))
    status_error = httpx.HTTPStatusError("too many", request=response.request, response=response)
    assert failure_code(status_error) == "RATE_LIMIT" and retry_after_ms(status_error) == 3000

    assert failure_code(TimeoutError()) == "TIMEOUT"
    assert failure_code(httpx.ReadTimeout("slow")) == "TIMEOUT"
    assert failure_code(httpx.ConnectError("refused")) == "TRANSPORT"
    assert failure_code(httpx.RemoteProtocolError("peer closed")) == "STREAM_CLOSED"
    assert failure_code(ValueError("nope")) == "UNKNOWN"

    try:  # the cause chain is followed: SDKs wrap transport failures
        try:
            raise httpx.ConnectError("refused")
        except httpx.ConnectError as exc:
            raise RuntimeError("request failed") from exc
    except RuntimeError as wrapped:
        assert failure_code(wrapped) == "TRANSPORT"
    assert retry_after_ms(ScriptedError(retry_after_ms=1500)) == 1500 and retry_after_ms(ValueError()) is None


def test_retry_policy():
    policy = RetryPolicy()
    assert policy.mode == "transient" and policy.codes == ["RATE_LIMIT", "SERVER", "TIMEOUT", "TRANSPORT"]
    assert policy.retries("SERVER") and not policy.retries("AUTH") and not policy.retries("EMPTY_RESPONSE")
    assert RetryPolicy(mode="all").retries("AUTH")
    assert RetryPolicy(codes=["EMPTY_RESPONSE", "EMPTY_RESPONSE"]).codes == ["EMPTY_RESPONSE"]
    with pytest.raises(ValueError, match="invalid failure code"):
        RetryPolicy(codes=["rate limit"])
    with pytest.raises(ValueError):
        RetryPolicy(max_retries=11)
    # Waits: 1s, 2s, 4s … capped; a longer wait the provider asked for wins, up to the cap.
    assert [policy.delay(n) for n in range(6)] == [1.0, 2.0, 4.0, 8.0, 16.0, 30.0]
    assert policy.delay(0, 5000) == 5.0 and policy.delay(3, 5000) == 8.0 and policy.delay(0, 900_000) == 30.0


def test_gemini_base_url_forms():
    for given in ("https://g.test", "https://g.test/", "https://g.test/v1beta", "https://g.test/v1"):
        assert translate_options("google_genai", {"base_url": given})["base_url"] == "https://g.test"
    assert translate_options("openai", {"base_url": "https://o.test/v1"})["base_url"] == "https://o.test/v1"


# ---------------------------------------------------------------------- retry policy
async def test_transient_failures_are_retried(profile):
    replies = [
        {"error": {"code": "RATE_LIMIT", "message": "slow down"}},
        {"error": {"status_code": 503}},
        {"content": "ok"},
    ]
    retries = []
    async with Harness(profile, patch=patch(replies, {"retry": FAST})) as h, client(h) as c:
        h.ctx.on("agent/model-retry", lambda retry: retries.append((retry.attempt, retry.code)))
        sid = (await c.post("/api/sessions", json={})).json()["id"]
        events = sse((await c.post(f"/api/sessions/{sid}/messages", json={"content": "hi"})).text)
        seen = [e for e in events if e["type"] == "retry"]
        assert [(e["attempt"], e["max_retries"], e["code"], e["delay_ms"]) for e in seen] == [
            (1, 2, "RATE_LIMIT", 0),
            (2, 2, "SERVER", 0),
        ]
        assert "slow down" in seen[0]["message"]
        assert retries == [(1, "RATE_LIMIT"), (2, "SERVER")]
        assert text_of(events) == "ok" and events[-1]["outcome"] == "completed"
        turn = events[-1]["extras"]["turn"]
        assert turn["stats"]["retries"] == 2 and turn["stats"]["steps"] == 1 and "error" not in turn
        assert [r["code"] for r in turn["records"] if r["t"] == "retry"] == ["RATE_LIMIT", "SERVER"]
        detail = (await c.get(f"/api/sessions/{sid}")).json()
        assert detail["failure"] is None and [m["role"] for m in detail["messages"]] == ["human", "ai"]


async def test_retries_stop_at_the_limit_and_skip_other_codes(profile):
    replies = [{"error": {"code": "SERVER"}}] * 3 + [{"error": {"code": "AUTH", "message": "bad key"}}]
    async with Harness(profile, patch=patch(replies, {"retry": FAST})) as h, client(h) as c:
        sid = (await c.post("/api/sessions", json={})).json()["id"]
        events = sse((await c.post(f"/api/sessions/{sid}/messages", json={"content": "hi"})).text)
        assert [e["attempt"] for e in events if e["type"] == "retry"] == [1, 2]  # three attempts, then the failure
        error = next(e for e in events if e["type"] == "error")
        assert error["code"] == "SERVER" and error["continuable"] is True and events[-1]["outcome"] == "error"

        sid = (await c.post("/api/sessions", json={})).json()["id"]
        events = sse((await c.post(f"/api/sessions/{sid}/messages", json={"content": "hi"})).text)
        assert not [e for e in events if e["type"] == "retry"]  # AUTH is not a transient code
        error = next(e for e in events if e["type"] == "error")
        assert error["code"] == "AUTH" and "bad key" in error["message"] and error["continuable"] is False


async def test_a_route_policy_overrides_the_global_one(profile):
    llm = {
        "retry": FAST,
        "providers": {"scripted": {"retry": {"mode": "all", "max_retries": 1, "initial_delay_ms": 0}}},
    }
    replies = [{"error": {"code": "AUTH"}}, {"content": "in"}]
    async with Harness(profile, patch=patch(replies, llm)) as h, client(h) as c:
        assert h.get("llm").retry_policy("scripted:test").mode == "all"
        assert h.get("llm").retry_policy("echo:echo").max_retries == 2 and h.get("llm").retry_policy().mode == "all"
        sid = (await c.post("/api/sessions", json={})).json()["id"]
        events = sse((await c.post(f"/api/sessions/{sid}/messages", json={"content": "hi"})).text)
        assert [e["code"] for e in events if e["type"] == "retry"] == ["AUTH"] and text_of(events) == "in"


# ---------------------------------------------------------------------- continue a failed turn
async def test_a_failed_turn_continues_without_a_new_message(profile):
    replies = [{"error": {"code": "SERVER", "message": "upstream 500"}}, {"content": "recovered"}]
    scripted.CALLS.clear()
    async with Harness(profile, patch=patch(replies)) as h, client(h) as c:  # no retry policy: the turn fails
        sid = (await c.post("/api/sessions", json={})).json()["id"]
        assert (await c.post(f"/api/sessions/{sid}/retry")).status_code == 409  # nothing failed yet
        events = sse((await c.post(f"/api/sessions/{sid}/messages", json={"content": "do it"})).text)
        error = next(e for e in events if e["type"] == "error")
        assert error["code"] == "SERVER" and error["continuable"] is True
        failed = events[-1]["extras"]["turn"]
        assert failed["outcome"] == "error" and failed["error"]["code"] == "SERVER"
        assert failed["records"][-1] == {
            "t": "end",
            "at": failed["records"][-1]["at"],
            "outcome": "error",
            "code": "SERVER",
        }

        detail = (await c.get(f"/api/sessions/{sid}")).json()
        assert detail["failure"]["code"] == "SERVER" and detail["failure"]["continuable"] is True
        assert "upstream 500" in detail["failure"]["message"] and detail["failure"]["run_id"] == failed["run_id"]
        assert [m["role"] for m in detail["messages"]] == ["human"]

        r = await c.post(f"/api/sessions/{sid}/retry")
        assert r.status_code == 200, r.text
        events = sse(r.text)
        assert text_of(events) == "recovered" and events[-1]["outcome"] == "completed"
        assert events[-1]["extras"]["turn"]["kind"] == "retry"

        detail = (await c.get(f"/api/sessions/{sid}")).json()
        assert detail["failure"] is None
        assert [(m["role"], m["content"]) for m in detail["messages"]] == [
            ("human", "do it"),
            ("ai", "recovered"),
        ]
        assert [t["kind"] for t in detail["turns"]] == ["message", "retry"]
        assert (await c.post(f"/api/sessions/{sid}/retry")).status_code == 409  # the last turn completed
        # The model saw the user message once in each attempt: no message was added by the continuation.
        calls = [call["messages"] for call in scripted.CALLS if "messages" in call]
        assert [[m for m in call if m[0] == "human"] for call in calls] == [[("human", "do it")]] * 2


async def test_only_listed_failure_codes_continue(profile):
    assert "AUTH" not in CONTINUABLE_CODES and "EMPTY_RESPONSE" in CONTINUABLE_CODES
    async with Harness(profile, patch=patch([{"error": {"code": "AUTH"}}, {"content": "later"}])) as h, client(h) as c:
        sid = (await c.post("/api/sessions", json={})).json()["id"]
        await c.post(f"/api/sessions/{sid}/messages", json={"content": "hi"})
        failure = (await c.get(f"/api/sessions/{sid}")).json()["failure"]
        assert failure["code"] == "AUTH" and failure["continuable"] is False
        r = await c.post(f"/api/sessions/{sid}/retry")
        assert r.status_code == 409 and "AUTH" in r.json()["detail"]
        # A new message works as before, and the failure is gone with the next turn.
        events = sse((await c.post(f"/api/sessions/{sid}/messages", json={"content": "again"})).text)
        assert text_of(events) == "later" and (await c.get(f"/api/sessions/{sid}")).json()["failure"] is None


# ---------------------------------------------------------------------- settings
async def test_retry_settings_round_trip(profile):
    async with Harness(profile, patch=patch([{"content": "hi"}])) as h, client(h) as c:
        d = (await c.get("/api/settings/models")).json()
        assert d["retry"] is None and d["retry_choices"] == list(CONTINUABLE_CODES)
        assert [p["id"] for p in d["protocols"]][-1] == "gemini"

        r = await c.put("/api/settings/model-retry", json={"retry": {"max_retries": 4, "codes": ["SERVER", "TIMEOUT"]}})
        assert r.status_code == 200, r.text
        assert r.json()["retry"]["max_retries"] == 4 and r.json()["retry"]["codes"] == ["SERVER", "TIMEOUT"]
        assert (await c.put("/api/settings/model-retry", json={"retry": {"max_retries": 99}})).status_code == 422
        assert (await c.put("/api/settings/model-retry", json={"retry": {"codes": ["nope"]}})).status_code == 422

        r = await c.put(
            "/api/settings/models/alt", json={"type": "scripted", "models": [{"id": "m1"}], "retry": {"mode": "all"}}
        )
        assert r.status_code == 200, r.text
        assert r.json()["route"]["retry"]["mode"] == "all" and r.json()["route"]["retry"]["max_retries"] == 2
        assert (
            h.get("llm").retry_policy("alt:m1").mode == "all"
            and h.get("llm").retry_policy("scripted:test").max_retries == 4
        )
        r = await c.put("/api/settings/models/alt", json={"title": "Alt"})  # None keeps the policy
        assert r.json()["route"]["retry"]["mode"] == "all"

    saved = yaml.safe_load(profile.patch_path.read_text())
    assert next(e for e in saved if e["id"] == "llm")["config"]["retry"] == {
        "max_retries": 4,
        "codes": ["SERVER", "TIMEOUT"],
    }
    reopened = [e for e in patch([{"content": "hi"}]) if e["id"] != "llm"]  # llm configuration: the saved one
    async with Harness(profile, patch=reopened) as h, client(h) as c:
        d = (await c.get("/api/settings/models")).json()
        assert d["retry"]["max_retries"] == 4 and d["retry"]["codes"] == ["SERVER", "TIMEOUT"]
        assert next(r for r in d["routes"] if r["id"] == "alt")["retry"]["mode"] == "all"
        r = await c.put("/api/settings/models/alt", json={"retry": {"mode": "inherit"}})
        assert r.json()["route"]["retry"] is None and h.get("llm").retry_policy("alt:m1").max_retries == 4
        r = await c.put("/api/settings/model-retry", json={"retry": None})
        assert r.json()["retry"] is None and h.get("llm").retry_policy("alt:m1") is None


async def test_gemini_protocol_lists_models_and_builds_the_client(profile, monkeypatch):
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((str(request.url), request.headers.get("x-goog-api-key")))
        rows = [
            {
                "name": "models/gemini-9-pro",
                "displayName": "Gemini 9 Pro",
                "inputTokenLimit": 1048576,
                "outputTokenLimit": 65536,
                "supportedGenerationMethods": ["generateContent", "countTokens"],
            },
            {"name": "models/embedding-9", "displayName": "Embedding", "supportedGenerationMethods": ["embedContent"]},
        ]
        return httpx.Response(200, json={"models": rows})

    real = httpx.AsyncClient

    def mocked(**kwargs):
        kwargs.pop("trust_env", None)
        return real(transport=httpx.MockTransport(handler), **kwargs)

    async with Harness(profile, patch=patch([{"content": "hi"}])) as h, client(h) as c:
        llm = h.get("llm")
        monkeypatch.setattr("pyharness_llm.service.httpx.AsyncClient", mocked)
        for base in ("https://g.test", "https://g.test/v1beta"):
            found = await llm.list_models("gem", None, protocol="gemini", base_url=base, api_key="k-1")
            assert [m["id"] for m in found["models"]] == ["gemini-9-pro"]
            assert found["models"][0]["name"] == "Gemini 9 Pro" and found["models"][0]["context_window"] == 1048576
        assert seen == [("https://g.test/v1beta/models?pageSize=1000", "k-1")] * 2
        monkeypatch.undo()

        body = {
            "protocol": "gemini",
            "base_url": "https://g.test/v1beta",
            "api_key": "k-1",
            "models": [{"id": "gemini-9-pro"}],
        }
        r = await c.put("/api/settings/models/gem", json=body)
        assert r.status_code == 200, r.text
        assert r.json()["route"]["type"] == "google_genai" and r.json()["route"]["protocol"] == "gemini"
        model = llm.resolve("gem:gemini-9-pro")
        assert type(model).__name__ == "ChatGoogleGenerativeAI" and model.base_url == "https://g.test"
