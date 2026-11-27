"""
AI subscriptions: the loopback OAuth flow, stores, Responses translation, provider parsing with
mocked HTTP, token refresh, model routes and the page routes.
"""

from __future__ import annotations

import base64
import json
import time
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from pyxis_harness import Harness, Profile
from pyxis_harness_subscriptions import SubscriptionsService
from pyxis_harness_subscriptions.chatgpt import ChatGPTProvider
from pyxis_harness_subscriptions.common import LlmError, http_error, jwt_claims, reset_delay_ms
from pyxis_harness_subscriptions.oauth import FlowSpec, LoginAttempt, LoginError
from pyxis_harness_subscriptions.responses import ResponsesTranslator, to_responses_input
from pyxis_harness_subscriptions.store import AuthStore, CatalogCache, ProviderSettings

HTTP_OFF = {"id": "http", "config": {"serve": False}}


def fake_jwt(claims: dict[str, Any]) -> str:
    enc = lambda d: base64.urlsafe_b64encode(json.dumps(d).encode()).decode().rstrip("=")  # noqa: E731
    return f"{enc({'alg': 'none'})}.{enc(claims)}.sig"


async def test_loopback_login_flow():
    spec = FlowSpec(
        provider="x",
        authorize_url="https://auth.example/authorize",
        host="127.0.0.1",
        ports=(0,),
        callback_path="/cb",
        scope="openid",
        client_id="cid",
        extra_params={"foo": "bar"},
    )
    attempt = LoginAttempt(spec)
    url = await attempt.start()
    q = parse_qs(urlparse(url).query)
    assert (
        q["client_id"] == ["cid"]
        and q["code_challenge_method"] == ["S256"]
        and q["foo"] == ["bar"]
        and q["state"] == [attempt.state]
    )
    assert attempt.redirect_uri.startswith("http://127.0.0.1:") and not attempt.manual_only
    async with httpx.AsyncClient() as c:
        bad = await c.get(attempt.redirect_uri, params={"state": "nope", "code": "c"})
        assert bad.status_code == 400 and "state mismatch" in bad.text
        assert (await c.get(attempt.redirect_uri.replace("/cb", "/other"))).status_code == 404
        ok = await c.get(attempt.redirect_uri, params={"state": attempt.state, "code": "the-code", "extra": "1"})
        assert ok.status_code == 200 and "Login successful" in ok.text
    cb = await attempt.wait()
    assert cb.code == "the-code" and cb.query["extra"] == "1"
    # Manual input accepts the full URL, a query string or a bare code; cancel and timeout reject.
    a2 = LoginAttempt(
        FlowSpec(
            provider="x",
            authorize_url="https://auth.example/authorize",
            host="127.0.0.1",
            ports=(0,),
            callback_path="/cb",
            client_id="cid",
            timeout=0.3,
        )
    )
    await a2.start()
    with pytest.raises(LoginError, match="does not match"):
        a2.manual("https://evil.example/cb?code=x&state=" + a2.state)
    a2.manual(f"{a2.redirect_uri}?code=manual-code&state={a2.state}")
    assert (await a2.wait()).code == "manual-code"
    a3 = LoginAttempt(
        FlowSpec(
            provider="x",
            authorize_url="https://auth.example/authorize",
            host="127.0.0.1",
            ports=(0,),
            callback_path="/cb",
            client_id="cid",
            timeout=0.3,
        )
    )
    await a3.start()
    with pytest.raises(LoginError, match="timed out"):
        await a3.wait()
    a4 = LoginAttempt(
        FlowSpec(
            provider="x",
            authorize_url="https://auth.example/authorize",
            host="127.0.0.1",
            ports=(0,),
            callback_path="/cb",
            client_id="cid",
        )
    )
    await a4.start()
    a4.cancel()
    with pytest.raises(LoginError, match="cancelled"):
        await a4.wait()


def test_stores(tmp_path):
    auth = AuthStore(tmp_path)
    assert auth.accounts("chatgpt") == {} and auth.default_key("chatgpt") is None
    auth.save("chatgpt", "a", {"accessToken": "1"})
    auth.save("chatgpt", "b", {"accessToken": "2"})
    assert auth.default_key("chatgpt") == "a" and auth.ordered_keys("chatgpt") == ["a", "b"]
    assert (
        auth.set_default("chatgpt", "b")
        and auth.ordered_keys("chatgpt") == ["b", "a"]
        and not auth.set_default("chatgpt", "zzz")
    )
    assert auth.delete("chatgpt", "b") and auth.default_key("chatgpt") == "a" and not auth.delete("chatgpt", "b")
    # A section of a provider outside PROVIDERS is dropped when the store opens.
    auth.file.update(lambda data: data.update(codex={"default": "x", "accounts": {"x": {"refreshToken": "r"}}}))
    assert set(AuthStore(tmp_path).file.read()) == {"chatgpt"}
    prefs = ProviderSettings(tmp_path)
    assert prefs.get("chatgpt") == {"accounts": {}, "contextWindows": {}}
    prefs.set(
        "chatgpt",
        {
            "visibleModels": ["gpt-5.1"],
            "contextWindows": {"gpt-5.1": 200000, "bad": "x"},
            "tools": {"web_search": False},
            "accounts": {"a": {"alias": "work", "other": 1}},
        },
    )
    assert prefs.get("chatgpt") == {
        "visibleModels": ["gpt-5.1"],
        "contextWindows": {"gpt-5.1": 200000},
        "accounts": {"a": {"alias": "work"}},
    }
    cache = CatalogCache(tmp_path)
    cache.set("chatgpt", [{"id": "gpt-5.1", "name": "GPT-5.1"}], "acct")
    assert cache.fresh("chatgpt", "acct") and cache.get("chatgpt", "acct")["models"][0]["id"] == "gpt-5.1"
    cache.clear("chatgpt")
    assert cache.get("chatgpt", "acct") is None


def test_common_helpers():
    assert (
        http_error("x", 401, "").code == "AUTH"
        and http_error("x", 429, "{}").code == "RATE_LIMIT"
        and http_error("x", 503, "oops").code == "SERVER"
    )
    assert (
        http_error("x", 400, "maximum context length exceeded").code == "CONTEXT_WINDOW_EXCEEDED"
        and http_error("x", 418, "").code == "HTTP_418"
    )
    assert reset_delay_ms(json.dumps({"error": {"resets_in_seconds": 30}})) == 32000
    assert reset_delay_ms(json.dumps({"reset_at": int(time.time()) + 100})) >= 100000 and reset_delay_ms("nope") is None
    assert jwt_claims(fake_jwt({"a": 1})) == {"a": 1} and jwt_claims("junk") == {}


def test_responses_input_and_translation():
    messages = [
        SystemMessage(content="be brief"),
        HumanMessage(content="hi"),
        AIMessage(content="", tool_calls=[{"name": "f", "args": {"a": 1}, "id": "c" * 70}]),
        ToolMessage(content="out", tool_call_id="c" * 70),
        AIMessage(content="", tool_calls=[{"name": "g", "args": {}, "id": "orphan"}]),
    ]
    instructions, items = to_responses_input(messages, repair=True, shorten_ids=True)
    assert instructions == "be brief" and items[0]["content"][0]["text"] == "hi"
    assert (
        items[1]["type"] == "function_call"
        and items[1]["call_id"].startswith("call_")
        and len(items[1]["call_id"]) == 64
        and items[2]["call_id"] == items[1]["call_id"]
    )
    assert items[-1]["type"] == "function_call_output" and "no recorded result" in items[-1]["output"]
    tr = ResponsesTranslator("t")
    events = [
        (
            "response.output_item.added",
            {
                "type": "response.output_item.added",
                "item": {"type": "function_call", "id": "it1", "call_id": "call_1", "name": "f"},
            },
        ),
        (None, {"type": "response.function_call_arguments.delta", "item_id": "it1", "delta": '{"a":'}),
        (None, {"type": "response.function_call_arguments.delta", "item_id": "it1", "delta": "1}"}),
        (None, {"type": "response.reasoning_summary_text.delta", "delta": "thinking"}),
        (None, {"type": "response.output_text.delta", "delta": "hello"}),
        (
            None,
            {
                "type": "response.completed",
                "response": {
                    "usage": {
                        "input_tokens": 10,
                        "output_tokens": 3,
                        "input_tokens_details": {"cached_tokens": 4},
                        "output_tokens_details": {"reasoning_tokens": 1},
                    }
                },
            },
        ),
    ]
    chunks = [c for ev, data in events for c in tr.feed(ev, json.dumps(data))]
    merged = chunks[0]
    for c in chunks[1:]:
        merged = merged + c
    assert merged.content == "hello" and merged.additional_kwargs["reasoning_content"] == "thinking"
    assert merged.tool_calls == [{"name": "f", "args": {"a": 1}, "id": "call_1", "type": "tool_call"}]
    assert (
        merged.usage_metadata["input_tokens"] == 10
        and merged.usage_metadata["input_token_details"]["cache_read"] == 4
        and merged.response_metadata["finish_reason"] == "tool_calls"
    )
    with pytest.raises(LlmError) as info:
        list(
            ResponsesTranslator("t").feed(
                None,
                json.dumps(
                    {"type": "response.failed", "error": {"code": "context_window_exceeded", "message": "too long"}}
                ),
            )
        )
    assert info.value.code == "CONTEXT_WINDOW_EXCEEDED"
    with pytest.raises(LlmError, match="no content"):
        list(ResponsesTranslator("t").feed(None, json.dumps({"type": "response.completed", "response": {}})))


CHATGPT_SESSION = {
    "accessToken": "at",
    "refreshToken": "rt",
    "clientId": "client-abc123",
    "subject": "user-1",
    "emailAddress": "ann@example.com",
    "planType": "plus",
    "scopes": ["openid", "chatgpt.tokens.use.direct"],
}


async def test_chatgpt_provider_with_mocked_http(tmp_path):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/accounts/oauth/token":
            form = {k: v[0] for k, v in parse_qs(request.content.decode()).items()}
            assert form["grant_type"] == "refresh_token" and form["client_id"] == "client-abc123"
            if form["refresh_token"] == "dead":
                return httpx.Response(400, json={"error": "invalid_grant"})
            return httpx.Response(200, json={"access_token": "at-fresh", "refresh_token": "rt2", "expires_in": 3600})
        if request.url.path == "/v1/models":
            assert request.headers["authorization"].startswith("Bearer at")
            return httpx.Response(
                200,
                json={
                    "models": [
                        {
                            "slug": "gpt-5.1",
                            "display_name": "GPT-5.1",
                            "context_window": 400000,
                            "max_context_window": 1000000,
                            "supported_reasoning_levels": [{"effort": "medium"}, {"effort": "high"}],
                            "default_reasoning_level": "medium",
                            "input_modalities": ["text", "image"],
                        },
                        {"slug": "hidden", "visibility": "hide"},
                    ]
                },
            )
        if request.url.path == "/v1/responses":
            body = json.loads(request.content)
            assert (
                body["instructions"].startswith("be brief")
                and body["model"] == "gpt-5.1"
                and body["reasoning"] == {"effort": "high", "summary": "auto"}
                and body["tools"][0]["type"] == "namespace"
                and body["tools"][0]["tools"][0]["name"] == "f"
            )
            events = [
                {"type": "response.output_text.delta", "delta": "pong"},
                {"type": "response.completed", "response": {"usage": {"input_tokens": 5, "output_tokens": 1}}},
            ]
            sse = "\n\n".join("data: " + json.dumps(e) for e in events) + "\n\n"
            return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=sse.encode())
        return httpx.Response(404, text="nope")

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = ChatGPTProvider(AuthStore(tmp_path), CatalogCache(tmp_path), http, {})
    key = CHATGPT_SESSION["clientId"]
    session = {**CHATGPT_SESSION, "expiresAt": int(time.time() * 1000) + 10**7}
    provider.auth.save("chatgpt", key, session)
    row = provider.account_rows()[0]
    assert row["account"] == "ann@example.com · abc123" and row["plan"] == "plus" and row["planEnabled"] is True
    models, available = await provider.models(key)
    assert (
        available
        and [m.id for m in models] == ["gpt-5.1"]
        and models[0].efforts == [{"id": "medium", "name": "Medium"}, {"id": "high", "name": "High"}]
        and models[0].input_modalities == ["text", "image"]
        and models[0].max_context_window == 1000000
    )
    assert provider.catalogs.fresh("chatgpt", key) and await provider.usage_cached(key) == {"supported": False}
    chat = provider.chat_model("gpt-5.1", key, reasoning_effort="high").bind_tools(
        [{"name": "f", "description": "d", "parameters": {"type": "object", "properties": {}}}]
    )
    result = await chat.ainvoke([SystemMessage(content="be brief"), HumanMessage(content="ping")])
    assert result.content == "pong" and result.usage_metadata["input_tokens"] == 5
    # A session without the plan scope has no catalog.
    provider.auth.save("chatgpt", key, {**session, "scopes": ["openid"]})
    assert await provider.models(key, force=True) == (models, False) and "plan usage is disabled" in provider.last_error
    # Refresh: an expired session refreshes once; a dead refresh token deletes the account.
    provider.auth.save("chatgpt", key, {**session, "expiresAt": 0})
    fresh = await provider.token_manager(key).session()
    assert fresh["accessToken"] == "at-fresh" and provider.auth.get("chatgpt", key)["refreshToken"] == "rt2"
    provider.auth.save("chatgpt", key, {**session, "expiresAt": 0, "refreshToken": "dead"})
    provider._managers.clear()
    with pytest.raises(LlmError) as info:
        await provider.token_manager(key).session()
    assert info.value.code == "INVALID_CREDENTIAL" and provider.auth.get("chatgpt", key) is None
    await http.aclose()


async def test_stream_idle_timeout_reaches_the_chat_models(home):
    profile = Profile.init("web", home=str(home))
    async with Harness(profile, patch=[HTTP_OFF]) as h:  # the default
        service = h.get("subscriptions")
        assert {p.chat_model("m", None).stream_idle_timeout for p in service.providers.values()} == {300.0}
    configured = [HTTP_OFF, {"id": "subscriptions", "config": {"stream_idle_timeout": 45}}]
    async with Harness(profile, patch=configured) as h:
        factory = h.get("llm")._providers["subscription"][0]
        model = factory("m", provider="chatgpt")
        assert model.stream_idle_timeout == 45.0
        assert model.bind_tools([]).stream_idle_timeout == 45.0  # a bound copy keeps it
    rejected = [HTTP_OFF, {"id": "subscriptions", "config": {"stream_idle_timeout": 0}}]
    async with Harness(profile, patch=rejected) as h:  # an invalid value fails the entry, not the boot
        assert h.ctx.get("subscriptions", None) is None


async def test_service_routes_and_model_routes(home):
    profile = Profile.init("web", home=str(home))
    async with Harness(profile, patch=[HTTP_OFF]) as h:
        service: SubscriptionsService = h.get("subscriptions")
        assert set(service.providers) == {"chatgpt"}
        llm = h.get("llm")
        assert "subscription" in llm.providers() and "chatgpt" not in llm.routes()
        # A subscription route saved in the configuration by an earlier version is dropped from it.
        llm.update(providers={"codex": {"type": "subscription", "models": [{"id": "old"}]}, "kept": {"type": "echo"}})
        # A stored ChatGPT session with a cached catalog becomes a model route.
        chatgpt = service.providers["chatgpt"]
        chatgpt.http = httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(404)))
        key = CHATGPT_SESSION["clientId"]
        chatgpt.auth.save("chatgpt", key, {**CHATGPT_SESSION, "expiresAt": int(time.time() * 1000) + 10**7})
        chatgpt.catalogs.set(
            "chatgpt",
            [
                {
                    "id": "gpt-5.1",
                    "name": "GPT-5.1",
                    "contextWindow": 400000,
                    "inputModalities": ["text", "image"],
                    "efforts": [{"id": "high", "name": "High"}],
                },
                {"id": "gpt-5.1-mini", "name": "GPT-5.1 mini", "contextWindow": 400000, "inputModalities": ["text"]},
            ],
            key,
        )
        await service.sync_routes(discover=False)
        # The route is published, not configured: the settings view does not list it and nothing saves it.
        assert list(llm.config.providers) == ["kept"] and llm.published() == {"chatgpt": "subscriptions"}
        assert [r["id"] for r in llm.describe()["routes"]] == ["kept"]
        route = llm.routes()["chatgpt"]
        assert (
            route.type == "subscription"
            and [m.id for m in route.models] == ["gpt-5.1", "gpt-5.1-mini"]
            and route.models[0].input == ["text", "image"]
        )
        directory = h.get("llm").directory()
        assert any(g["id"] == "chatgpt" and g["title"].startswith("ChatGPT") for g in directory["groups"])
        chat = h.get("llm").resolve("chatgpt:gpt-5.1")
        assert chat.label == "chatgpt" and chat.model_name == "gpt-5.1" and chat.provider_ref is chatgpt
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=h.get("http").app), base_url="http://t", timeout=30
        ) as c:
            st = (await c.get("/api/subscriptions/status")).json()["providers"]
            assert list(st) == ["chatgpt"] and st["chatgpt"]["accounts"] == [
                {
                    "key": key,
                    "account": "ann@example.com · abc123",
                    "plan": "plus",
                    "isDefault": True,
                    "expiresAt": st["chatgpt"]["accounts"][0]["expiresAt"],
                    "connected": True,
                    "planEnabled": True,
                }
            ]
            cat = (await c.get("/api/subscriptions/provider-settings", params={"provider": "chatgpt"})).json()
            assert (
                [m["id"] for m in cat["models"]] == ["gpt-5.1", "gpt-5.1-mini"]
                and "tools" not in cat
                and cat["accounts"][0]["label"] == "ann@example.com · abc123"
            )
            r = await c.put(
                "/api/subscriptions/provider-settings",
                json={
                    "provider": "chatgpt",
                    "settings": {"visibleModels": ["gpt-5.1"], "contextWindows": {"gpt-5.1": 128000}},
                },
            )
            assert r.json() == {"ok": True}
            route = h.get("llm").routes()["chatgpt"]
            assert [m.id for m in route.models] == ["gpt-5.1"] and route.models[0].context_window == 128000
            default = {"provider": "chatgpt", "model": "gpt-5.1", "effort": "high"}
            assert (await c.post("/api/subscriptions/model-default", json=default)).json() == {"ok": True}
            assert h.get("llm").resolve("chatgpt:gpt-5.1").reasoning_effort == "high"
            assert (
                await c.post("/api/subscriptions/model-default", json={**default, "model": "gpt-5.1-mini"})
            ).status_code == 400  # no efforts listed
            assert (
                await c.post("/api/subscriptions/default", json={"provider": "chatgpt", "account": "nobody"})
            ).status_code == 404
            for gone in ("codex", "grok", "antigravity", "nope"):
                assert (await c.post("/api/subscriptions/login", json={"provider": gone})).status_code == 400
            r = await c.post("/api/subscriptions/logout", json={"provider": "chatgpt", "account": key})
            assert r.json() == {"ok": True} and "chatgpt" not in h.get("llm").routes()
            assert (
                "Signed out locally"
                in (await c.get("/api/subscriptions/status")).json()["providers"]["chatgpt"]["detail"]
            )
        await chatgpt.http.aclose()
        assert not any("subscriptions" in r.tags for r in h.get("tools").records())
        assert any(cl["entry"] == "subscriptions" for cl in h.get("webui").clients())
