"""
AI subscriptions: the loopback OAuth flow, stores, Responses and Antigravity translation, provider parsing with
mocked HTTP, token refresh, model routes and the page routes.
"""

from __future__ import annotations

import asyncio
import base64
import json
import time
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from pyharness import Harness, Profile
from pyharness_subscriptions import SubscriptionsService
from pyharness_subscriptions.antigravity import AntigravityProvider
from pyharness_subscriptions.antigravity_client import CLI_VERSION_FALLBACK, build_user_agent, parse_cli_version
from pyharness_subscriptions.antigravity_wire import (
    AntigravityTranslator,
    build_request,
    efforts_for,
    simple_schema,
    thinking_config,
    to_contents,
)
from pyharness_subscriptions.codex import CodexProvider
from pyharness_subscriptions.codex_tools import SearchArgs, validate_commands
from pyharness_subscriptions.common import LlmError, http_error, jwt_claims, reset_delay_ms, session_uuid
from pyharness_subscriptions.grok import tier_name
from pyharness_subscriptions.oauth import FlowSpec, LoginAttempt, LoginError
from pyharness_subscriptions.responses import ResponsesTranslator, to_responses_input
from pyharness_subscriptions.store import AuthStore, CatalogCache, ProviderSettings

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
    assert auth.accounts("codex") == {} and auth.default_key("codex") is None
    auth.save("codex", "a", {"accessToken": "1"})
    auth.save("codex", "b", {"accessToken": "2"})
    assert auth.default_key("codex") == "a" and auth.ordered_keys("codex") == ["a", "b"]
    assert (
        auth.set_default("codex", "b")
        and auth.ordered_keys("codex") == ["b", "a"]
        and not auth.set_default("codex", "zzz")
    )
    assert auth.delete("codex", "b") and auth.default_key("codex") == "a" and not auth.delete("codex", "b")
    prefs = ProviderSettings(tmp_path)
    assert prefs.get("codex") == {"accounts": {}, "contextWindows": {}, "tools": {}}
    prefs.set(
        "codex",
        {
            "visibleModels": ["gpt-5.1"],
            "contextWindows": {"gpt-5.1": 200000, "bad": "x"},
            "tools": {"web_search": False},
        },
    )
    assert prefs.get("codex")["visibleModels"] == ["gpt-5.1"] and prefs.get("codex")["contextWindows"] == {
        "gpt-5.1": 200000
    }
    assert prefs.tool_enabled("codex", "web_search") is False and prefs.tool_enabled("codex", "image_generate") is True
    assert prefs.tool_enabled("codex", "web_search", at_ms=1) is True  # before the history entry
    with pytest.raises(ValueError, match="unknown tool"):
        prefs.set("codex", {"tools": {"x_search": True}})
    cache = CatalogCache(tmp_path)
    cache.set("grok", [{"id": "grok-4", "name": "Grok 4"}], "acct")
    assert cache.fresh("grok", "acct") and cache.get("grok", "acct")["models"][0]["id"] == "grok-4"
    cache.clear("grok")
    assert cache.get("grok", "acct") is None


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
    assert session_uuid("1e4b9b7a-0000-4000-8000-000000000000") == "1e4b9b7a-0000-4000-8000-000000000000"
    u = session_uuid("session-abc")
    assert u == session_uuid("session-abc") and u[14] == "8"
    assert tier_name({"tier": 3}) == "X Premium" and tier_name({"tier": 42}) == "42" and tier_name({}) is None


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


def test_antigravity_wire():
    assert (
        efforts_for("gemini-3.1-pro-preview") == ["low", "high"]
        and efforts_for("claude-sonnet-4") == ["high"]
        and efforts_for("gemini-2.5-flash") == ["low", "medium", "high"]
    )
    assert thinking_config("gemini-2.5-flash", "medium", 10000) == {
        "includeThoughts": True,
        "thinkingBudget": 4000,
    } and thinking_config("gemini-2.5-flash", "off", None) == {"includeThoughts": False, "thinkingBudget": 0}
    assert thinking_config("gemini-3.1-flash-image", "high", None) == {"thinkingLevel": "HIGH", "includeThoughts": True}
    with pytest.raises(LlmError, match="UNSUPPORTED|does not support"):
        thinking_config("claude-sonnet-4", "low", None)
    schema = {
        "type": "object",
        "properties": {
            "n": {"type": ["integer", "null"]},
            "k": {"anyOf": [{"type": "string", "enum": ["a", "b"]}, {"type": "null"}]},
        },
        "required": ["n"],
        "$schema": "x",
    }
    assert simple_schema(schema) == {
        "type": "object",
        "required": ["n"],
        "properties": {"n": {"type": "number"}, "k": {"type": "string", "enum": ["a", "b"]}},
    }
    messages = [
        SystemMessage(content="sys"),
        HumanMessage(content="hi"),
        AIMessage(content="", tool_calls=[{"name": "f", "args": {"a": 1}, "id": "c1"}]),
        ToolMessage(content='{"ok": true}', tool_call_id="c1"),
        HumanMessage(content="next"),
    ]
    system, contents = to_contents(messages, "gemini-3-flash")
    assert system == "sys" and [c["role"] for c in contents] == ["user", "model", "user"]
    assert contents[1]["parts"][0] == {
        "functionCall": {"id": "c1", "name": "f", "args": {"a": 1}},
        "thoughtSignature": "skip_thought_signature_validator",
    }
    assert contents[2]["parts"][0]["functionResponse"] == {
        "id": "c1",
        "name": "f",
        "response": {"ok": True},
    } and contents[2]["parts"][1] == {"text": "next"}
    req = build_request(
        project="p", model="claude-sonnet-4", session_id="s", messages=messages, tools=[], max_tokens=70000, effort=None
    )
    assert (
        req["request"]["generationConfig"]["maxOutputTokens"] == 64000
        and req["project"] == "p"
        and "tools" not in req["request"]
    )
    tr = AntigravityTranslator("ag")
    chunks = list(
        tr.feed(
            json.dumps(
                {
                    "response": {
                        "candidates": [
                            {
                                "content": {
                                    "parts": [
                                        {"thought": True, "text": "hmm"},
                                        {"text": "hello"},
                                        {"functionCall": {"id": "x", "name": "f", "args": {"q": 1}}},
                                    ]
                                },
                                "finishReason": "STOP",
                            }
                        ],
                        "usageMetadata": {
                            "promptTokenCount": 9,
                            "cachedContentTokenCount": 2,
                            "candidatesTokenCount": 4,
                            "thoughtsTokenCount": 1,
                        },
                    }
                }
            )
        )
    )
    merged = chunks[0]
    for c in chunks[1:]:
        merged = merged + c
    assert (
        merged.content == "hello"
        and merged.additional_kwargs["reasoning_content"] == "hmm"
        and merged.tool_calls[0]["args"] == {"q": 1}
    )
    assert merged.usage_metadata == {
        "input_tokens": 9,
        "output_tokens": 4,
        "total_tokens": 13,
        "input_token_details": {"cache_read": 2},
        "output_token_details": {"reasoning": 1},
    }
    with pytest.raises(LlmError, match="blocked"):
        list(
            AntigravityTranslator("ag").feed(
                json.dumps({"candidates": [{"content": {"parts": [{"text": "x"}]}, "finishReason": "SAFETY"}]})
            )
        )


async def test_antigravity_cli_signature(tmp_path):
    assert (
        build_user_agent("1.5.3", "win32", "AMD64")
        == "antigravity/cli/1.5.3 (aidev_client; os_type=windows; arch=amd64; cl=962369648; auth_method=consumer)"
    )
    assert parse_cli_version("Antigravity CLI auto updater is running! Stable Version: 1.6.0. Rolled out") == "1.6.0"
    assert parse_cli_version("maintenance") is None
    calls: list[str] = []
    answer = {"status": 200, "text": "Stable Version: 1.6.0."}

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        if request.url.host.startswith("antigravity-cli-auto-updater"):
            return httpx.Response(answer["status"], text=answer["text"])
        return httpx.Response(200, json={"ua": request.headers["user-agent"]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        provider = AntigravityProvider(AuthStore(tmp_path), CatalogCache(tmp_path), http)
        assert provider.user_agent().startswith(f"antigravity/cli/{CLI_VERSION_FALLBACK} (aidev_client; os_type=")
        # The first signed request reads the stable version once; later requests reuse it.
        reply = await provider.call({"accessToken": "t"}, "loadCodeAssist", {}, single_origin=True)
        assert reply["ua"].startswith("antigravity/cli/1.6.0 (aidev_client; ")
        await provider.call({"accessToken": "t"}, "loadCodeAssist", {}, single_origin=True)
        assert sum("auto-updater" in url for url in calls) == 1
        # A failed read keeps the pinned version; a configured User-Agent replaces the signature and reads nothing.
        answer["status"] = 503
        down = AntigravityProvider(AuthStore(tmp_path), CatalogCache(tmp_path), http)
        assert (await down.call({"accessToken": "t"}, "x", {}, single_origin=True))["ua"].startswith(
            f"antigravity/cli/{CLI_VERSION_FALLBACK} "
        )
        before = len(calls)
        custom = AntigravityProvider(
            AuthStore(tmp_path), CatalogCache(tmp_path), http, {"antigravity": {"userAgent": "my-agent/1"}}
        )
        assert (await custom.call({"accessToken": "t"}, "x", {}, single_origin=True))["ua"] == "my-agent/1"
        assert len(calls) == before + 1
    # A rejected signature is answered with HTTP 200 and a notice as the only content.
    notice = "This version of Antigravity is no longer supported. Please download and install the latest version"
    part = {"response": {"candidates": [{"content": {"parts": [{"text": notice}]}, "finishReason": "STOP"}]}}
    with pytest.raises(LlmError, match="rejected the client signature") as info:
        list(AntigravityTranslator("ag").feed(json.dumps(part)))
    assert info.value.code == "UNSUPPORTED_CLIENT"
    fine = {"response": {"candidates": [{"content": {"parts": [{"text": "This version of the plan is fine."}]}}]}}
    assert list(AntigravityTranslator("ag").feed(json.dumps(fine)))[0].content == "This version of the plan is fine."


def test_codex_search_commands():
    assert validate_commands(SearchArgs(query="cats")) == {"search_query": [{"q": "cats"}]}
    with pytest.raises(ValueError, match="at least one"):
        validate_commands(SearchArgs())
    with pytest.raises(ValueError, match="response_length"):
        validate_commands(SearchArgs(search_query=[{"q": str(i)} for i in range(4)]))
    with pytest.raises(ValueError, match="cannot be combined"):
        validate_commands(SearchArgs(query="x", time=[{"utc_offset": "+08:00"}]))


def _mock_transport(handler: Any) -> httpx.MockTransport:
    return httpx.MockTransport(handler)


async def test_codex_provider_with_mocked_http(tmp_path):
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(f"{request.method} {request.url.path}")
        if request.url.path == "/oauth/token":
            body = (
                json.loads(request.content)
                if request.headers.get("content-type", "").startswith("application/json")
                else parse_qs(request.content.decode())
            )
            grant = (
                body.get("grant_type")
                if isinstance(body, dict) and not isinstance(body.get("grant_type"), list)
                else body["grant_type"][0]
            )
            if grant == "refresh_token" and (body.get("refresh_token") == "dead"):
                return httpx.Response(400, json={"error": {"code": "refresh_token_expired"}})
            id_token = fake_jwt(
                {
                    "email": "ann@example.com",
                    "https://api.openai.com/auth": {
                        "chatgpt_account_id": "acct1",
                        "chatgpt_user_id": "u1",
                        "chatgpt_plan_type": "plus",
                    },
                }
            )
            return httpx.Response(
                200,
                json={"access_token": "at-" + grant, "refresh_token": "rt2", "expires_in": 3600, "id_token": id_token},
            )
        if "codex/latest" in str(request.url):
            return httpx.Response(200, json={"version": "0.160.0"})
        if request.url.path == "/backend-api/codex/models":
            assert request.headers["chatgpt-account-id"] == "acct1" and request.url.params["client_version"] in (
                "0.160.0",
                "0.153.4",
            )
            return httpx.Response(
                200,
                json={
                    "models": [
                        {
                            "slug": "gpt-5.1-codex",
                            "display_name": "GPT-5.1 Codex",
                            "context_window": 400000,
                            "max_context_window": 400000,
                            "supported_reasoning_levels": [{"effort": "medium"}, {"effort": "xhigh"}],
                            "default_reasoning_level": "medium",
                            "service_tiers": [{"id": "priority"}],
                            "visibility": "list",
                            "priority": 2,
                        },
                        {"slug": "hidden", "visibility": "hide"},
                        {"slug": "gpt-5.1", "display_name": "GPT-5.1", "priority": 1},
                    ]
                },
            )
        if request.url.path == "/backend-api/wham/usage":
            return httpx.Response(
                200,
                json={
                    "plan_type": "plus",
                    "rate_limit": {
                        "primary_window": {
                            "used_percent": 12.5,
                            "limit_window_seconds": 18000,
                            "reset_after_seconds": 100,
                        },
                        "secondary_window": {
                            "used_percent": 40,
                            "limit_window_seconds": 604800,
                            "reset_at": 1800000000,
                        },
                    },
                },
            )
        if request.url.path == "/backend-api/codex/responses":
            body = json.loads(request.content)
            assert (
                body["instructions"].startswith("be brief")
                and body["tools"][0]["name"] == "f"
                and request.headers["session-id"]
                and body["prompt_cache_key"] == "sess-1"
            )
            sse = (
                "\n\n".join(
                    "data: " + json.dumps(e)
                    for e in [
                        {"type": "response.output_text.delta", "delta": "pong"},
                        {"type": "response.completed", "response": {"usage": {"input_tokens": 5, "output_tokens": 1}}},
                    ]
                )
                + "\n\n"
            )
            return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=sse.encode())
        if request.url.path == "/backend-api/codex/alpha/search":
            return httpx.Response(
                200,
                json={
                    "output": "Cats are great.",
                    "results": [
                        {"url": "https://a.example", "title": "A", "snippet": "s"},
                        {"url": "https://a.example"},
                        {"url": "ftp://x"},
                    ],
                    "truncated": True,
                },
            )
        return httpx.Response(404, text="nope")

    http = httpx.AsyncClient(transport=_mock_transport(handler))
    provider = CodexProvider(AuthStore(tmp_path), CatalogCache(tmp_path), http, {})
    attempt = LoginAttempt(
        FlowSpec(
            provider="codex",
            authorize_url="https://auth.openai.com/oauth/authorize",
            host="127.0.0.1",
            ports=(0,),
            callback_path="/auth/callback",
            client_id="x",
        )
    )
    await attempt.start()
    key, session = await provider.exchange(attempt, "code", {})
    await attempt.close()
    assert (
        key == json.dumps(["acct1", "user", "u1"])
        and session["accountId"] == "acct1"
        and session["planType"] == "plus"
        and session["emailAddress"] == "ann@example.com"
    )
    provider.auth.save("codex", key, session)
    assert provider.account_rows()[0]["account"] == "ann@example.com" and provider.account_rows()[0]["plan"] == "plus"
    models, available = await provider.models(key)
    assert (
        available
        and [m.id for m in models] == ["gpt-5.1", "gpt-5.1-codex"]
        and models[1].efforts == [{"id": "medium", "name": "Medium"}, {"id": "xhigh", "name": "Extra High"}]
        and models[1].fast_tier is True
    )
    assert provider.catalogs.fresh("codex", key)
    usage = await provider.usage_cached(key)
    assert (
        usage["plan"] == "plus"
        and [w["kind"] for w in usage["windows"]] == ["session", "weekly"]
        and usage["windows"][1]["resetsAt"] == 1800000000000
    )
    chat = (
        provider.chat_model("gpt-5.1-codex", key)
        .bind_tools([{"name": "f", "description": "d", "parameters": {"type": "object", "properties": {}}}])
        .model_copy(update={"session_id_hint": "sess-1"})
    )
    result = await chat.ainvoke(
        [SystemMessage(content="be brief"), HumanMessage(content="ping")],
        config={"configurable": {"thread_id": "sess-1"}},
    )
    assert result.content == "pong" and result.usage_metadata["input_tokens"] == 5
    # Refresh: an expired session refreshes once; a dead refresh token deletes the account.
    provider.auth.save("codex", key, {**session, "expiresAt": 0})
    fresh = await provider.token_manager(key).session()
    assert (
        fresh["accessToken"] == "at-refresh_token"
        and provider.auth.get("codex", key)["accessToken"] == "at-refresh_token"
    )
    provider.auth.save("codex", key, {**session, "expiresAt": 0, "refreshToken": "dead"})
    provider._managers.clear()
    with pytest.raises(LlmError) as info:
        await provider.token_manager(key).session()
    assert info.value.code == "INVALID_CREDENTIAL" and provider.auth.get("codex", key) is None
    await http.aclose()


async def test_service_routes_and_model_routes(home, tmp_path, monkeypatch):
    profile = Profile.init("web", home=str(home))
    async with Harness(profile, patch=[HTTP_OFF]) as h:
        service: SubscriptionsService = h.get("subscriptions")
        assert set(service.providers) == {"codex", "chatgpt", "antigravity", "grok"}
        assert "subscription" in h.get("llm").providers() and not any(
            r in h.get("llm").config.providers for r in service.providers
        )
        # A stored Grok session with a cached catalog becomes a model route and registers the Grok tools.
        grok = service.providers["grok"]
        grok.auth.save(
            "grok",
            "ann@x.ai",
            {
                "accessToken": fake_jwt({"tier": 1}),
                "refreshToken": "r",
                "expiresAt": int(time.time() * 1000) + 10**7,
                "account": "ann@x.ai",
            },
        )
        grok.catalogs.set(
            "grok",
            [
                {"id": "grok-4", "name": "Grok 4", "contextWindow": 256000, "inputModalities": ["text", "image"]},
                {
                    "id": "grok-code-fast-1",
                    "name": "Grok Code Fast 1",
                    "contextWindow": 256000,
                    "inputModalities": ["text"],
                },
            ],
            "ann@x.ai",
        )
        await service.sync_routes(discover=False)
        service.sync_tools()
        route = h.get("llm").config.providers["grok"]
        assert (
            route.type == "subscription"
            and [m.id for m in route.models] == ["grok-4", "grok-code-fast-1"]
            and route.models[0].input == ["text", "image"]
        )
        directory = h.get("llm").directory()
        assert any(g["id"] == "grok" and g["title"].startswith("Grok") for g in directory["groups"])
        chat = h.get("llm").resolve("grok:grok-4")
        assert chat.label == "grok" and chat.model_name == "grok-4" and chat.provider_ref is grok
        assert {"grok_x_search", "grok_image_generate", "grok_video_generate"} <= {
            t.name for t in h.get("tools").list()
        }
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=h.get("http").app), base_url="http://t", timeout=30
        ) as c:
            st = (await c.get("/api/subscriptions/status")).json()["providers"]
            assert (
                st["grok"]["accounts"]
                == [
                    {
                        "key": "ann@x.ai",
                        "account": "ann@x.ai",
                        "plan": "SuperGrok",
                        "isDefault": True,
                        "expiresAt": st["grok"]["accounts"][0]["expiresAt"],
                        "connected": True,
                    }
                ]
                and st["codex"]["accounts"] == []
                and "clientVersion" in st["codex"]
            )
            cat = (await c.get("/api/subscriptions/provider-settings", params={"provider": "grok"})).json()
            assert (
                [m["id"] for m in cat["models"]] == ["grok-4", "grok-code-fast-1"]
                and cat["tools"] == ["image_generate", "video_generate", "x_search"]
                and cat["accounts"][0]["label"] == "ann@x.ai"
            )
            r = await c.put(
                "/api/subscriptions/provider-settings",
                json={
                    "provider": "grok",
                    "settings": {
                        "visibleModels": ["grok-4"],
                        "contextWindows": {"grok-4": 128000},
                        "tools": {"x_search": False},
                    },
                },
            )
            assert r.json() == {"ok": True}
            route = h.get("llm").config.providers["grok"]
            assert [m.id for m in route.models] == ["grok-4"] and route.models[0].context_window == 128000
            assert (
                service.tool_enabled("grok", "x_search") is False
                and service.tool_enabled("grok", "image_generate") is True
            )
            assert (
                await c.put(
                    "/api/subscriptions/provider-settings",
                    json={"provider": "grok", "settings": {"tools": {"web_search": True}}},
                )
            ).status_code == 400
            assert (
                await c.post(
                    "/api/subscriptions/model-default", json={"provider": "grok", "model": "grok-4", "effort": "high"}
                )
            ).status_code == 400  # no efforts listed
            assert (
                await c.post("/api/subscriptions/default", json={"provider": "grok", "account": "nobody"})
            ).status_code == 404
            assert (await c.post("/api/subscriptions/login", json={"provider": "nope"})).status_code == 400
            assert (await c.get("/api/subscriptions/media/../etc/passwd")).status_code == 404
            assert (await c.get("/api/subscriptions/media/missing.png")).status_code == 404
            r = await c.post("/api/subscriptions/logout", json={"provider": "grok", "account": "ann@x.ai"})
            assert (
                r.json() == {"ok": True}
                and "grok" not in h.get("llm").config.providers
                and not any(t.name.startswith("grok_") for t in h.get("tools").list())
            )
        assert any(cl["entry"] == "subscriptions" for cl in h.get("webui").clients())
    asyncio.get_event_loop()
