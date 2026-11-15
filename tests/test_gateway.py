"""
API gateway: protocol translation, the stores, the gateway application, stream normalization and the management
routes.
"""

from __future__ import annotations

import asyncio
import json
import logging
import stat
import time
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage, ToolMessage

from pyharness import Harness, Profile
from pyharness_gateway import anthropic_messages, openai_chat, openai_responses
from pyharness_gateway.backend import LangChainBackend, UpstreamError
from pyharness_gateway.chunks import BlockAssembler, normalize
from pyharness_gateway.drafts import GatewayError, Generation, materialize
from pyharness_gateway.images import ImageResolver, sniff_media_type
from pyharness_gateway.keys import KeyStore, KeyStoreError, presented_key
from pyharness_gateway.listener import Listener
from pyharness_gateway.models import ModelCatalog, ModelResolutionError, Target
from pyharness_gateway.server import GatewayDeps, create_app
from pyharness_gateway.settings import SettingsError, SettingsStore
from pyharness_gateway.usage import UsageStore, parse_filter, range_start

HTTP_OFF = {"id": "http", "config": {"serve": False}}
USAGE = {"input_tokens": 10, "output_tokens": 5, "cache_read_tokens": 2, "reasoning_tokens": 1}

# A reasoning block, a text block, a tool call and usage, as the backend streams them.
SAMPLE = [
    {"type": "block-start", "index": 0, "block_type": "reasoning"},
    {"type": "reasoning-delta", "index": 0, "text": "thinking"},
    {"type": "block-end", "index": 0},
    {"type": "block-start", "index": 1, "block_type": "text"},
    {"type": "text-delta", "index": 1, "text": "Hel"},
    {"type": "text-delta", "index": 1, "text": "lo"},
    {"type": "block-end", "index": 1},
    {"type": "block-start", "index": 2, "block_type": "tool-call"},
    {"type": "tool-call-delta", "index": 2, "id": "call_1", "name": "get_weather", "arguments_delta": '{"city":'},
    {"type": "tool-call-delta", "index": 2, "id": "call_1", "arguments_delta": '"Paris"}'},
    {"type": "block-end", "index": 2},
    {"type": "usage", "usage": USAGE},
    {"type": "finish", "reason": {"kind": "tool-calls"}},
]
QUOTA = {"type": "finish", "reason": {"kind": "error", "failure": {"code": "QUOTA", "message": "quota", "status": 429}}}


def frames(text: str) -> list[dict[str, Any]]:
    out = []
    for part in filter(str.strip, text.split("\n\n")):
        lines = part.split("\n")
        event = next((line[7:] for line in lines if line.startswith("event: ")), None)
        data = "\n".join(line[6:] for line in lines if line.startswith("data: "))
        out.append({"event": event, "data": data if data == "[DONE]" else json.loads(data)})
    return out


def encoded(encoder: Any) -> list[dict[str, Any]]:
    return frames(encoder.start() + "".join(encoder.push(chunk) for chunk in SAMPLE) + encoder.end())


async def no_images(image: dict[str, Any]) -> str:
    raise AssertionError("no images expected")


def rejects(parse: Any, body: Any) -> None:
    with pytest.raises(GatewayError) as info:
        parse(body)
    assert info.value.status == 400, body


# ---------------------------------------------------------------------- translation
async def test_chat_completions_parse_and_materialize():
    parsed = openai_chat.parse_request(
        {
            "model": "deepseek:deepseek-chat",
            "stream": True,
            "stream_options": {"include_usage": True},
            "temperature": 0.5,
            "max_completion_tokens": 200,
            "stop": "END",
            "messages": [
                {"role": "system", "content": "Be brief."},
                {"role": "developer", "content": [{"type": "text", "text": "Reply in English."}]},
                {"role": "user", "content": [{"type": "text", "text": "Weather?"}]},
                {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call_1",
                            "type": "function",
                            "function": {"name": "get_weather", "arguments": '{"city":"Paris"}'},
                        }
                    ],
                },
                {"role": "tool", "tool_call_id": "call_1", "content": "Sunny"},
            ],
            "tools": [
                {
                    "type": "function",
                    "function": {
                        "name": "get_weather",
                        "description": "Weather",
                        "parameters": {"type": "object", "properties": {"city": {"type": "string"}}},
                    },
                }
            ],
        }
    )
    assert parsed.system == "Be brief.\n\nReply in English."
    assert parsed.include_usage and parsed.stop == ["END"] and parsed.max_tokens == 200
    assert [m["role"] for m in parsed.messages] == ["user", "assistant", "tool"]
    call = {"type": "tool-call", "id": "call_1", "name": "get_weather", "arguments": '{"city":"Paris"}'}
    assert parsed.messages[1] == {"role": "assistant", "content": [call]}

    generation = await materialize(parsed, Target("deepseek", "deepseek-chat"), no_images)
    assert generation.target.id == "deepseek:deepseek-chat" and generation.temperature == 0.5
    assert generation.tools[0]["function"]["name"] == "get_weather"
    system, user, assistant, tool = generation.messages
    assert system.content == parsed.system and user.content == "Weather?"
    assert assistant.tool_calls[0]["args"] == {"city": "Paris"} and assistant.tool_calls[0]["id"] == "call_1"
    assert isinstance(tool, ToolMessage) and tool.tool_call_id == "call_1" and tool.content == "Sunny"

    base = {"messages": [{"role": "user", "content": "hi"}]}
    for body in (
        {**base, "n": 2},
        {**base, "logprobs": True},
        {**base, "response_format": {"type": "json_schema", "json_schema": {}}},
        {**base, "tools": [{"type": "web_search"}]},
        {"messages": []},
        {"messages": [{"role": "function", "content": "x"}]},
    ):
        rejects(openai_chat.parse_request, body)
    images = openai_chat.parse_request(
        {
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}},
                        {"type": "image_url", "image_url": "https://example.com/a.png"},
                    ],
                }
            ]
        }
    )
    assert images.messages[0]["content"] == [
        {"type": "pending-image", "source": {"kind": "base64", "media_type": "image/png", "data": "AAAA"}},
        {"type": "pending-image", "source": {"kind": "url", "url": "https://example.com/a.png"}},
    ]
    with_image = await materialize(
        images, Target("x", "y"), lambda image: asyncio.sleep(0, "data:image/png;base64,QQ==")
    )
    assert [part["type"] for part in with_image.messages[0].content] == ["image_url", "image_url"]


def test_chat_completions_stream_and_complete_object():
    out = encoded(openai_chat.ChatStreamEncoder("deepseek:deepseek-chat", True))
    assert out[-1]["data"] == "[DONE]"
    deltas = [frame["data"] for frame in out[:-1]]
    first = deltas[0]["choices"][0]["delta"]
    assert first["role"] == "assistant" and first["reasoning_content"] == "thinking"
    assert "".join(d["choices"][0]["delta"].get("content", "") for d in deltas if d["choices"]) == "Hello"
    tools = [call for d in deltas if d["choices"] for call in d["choices"][0]["delta"].get("tool_calls", [])]
    assert tools[0]["id"] == "call_1" and tools[0]["index"] == 0 and tools[0]["function"]["name"] == "get_weather"
    assert "".join(call["function"]["arguments"] for call in tools) == '{"city":"Paris"}'
    assert deltas[-2]["choices"][0]["finish_reason"] == "tool_calls"
    assert deltas[-1]["choices"] == [] and deltas[-1]["usage"]["prompt_tokens"] == 10

    blocks = [
        {"type": "text", "text": "Hello"},
        {"type": "tool-call", "id": "call_1", "name": "get_weather", "arguments": "{}"},
    ]
    complete = openai_chat.completion("deepseek:deepseek-chat", blocks, USAGE, {"kind": "tool-calls"})
    choice = complete["choices"][0]
    assert choice["finish_reason"] == "tool_calls" and choice["message"]["content"] == "Hello"
    assert len(choice["message"]["tool_calls"]) == 1 and complete["usage"]["total_tokens"] == 15


def test_responses_parse_and_stream():
    parsed = openai_responses.parse_request(
        {
            "model": "x:y",
            "instructions": "Be helpful.",
            "input": [
                {"role": "user", "content": "Weather?"},
                {"type": "function_call", "call_id": "call_1", "name": "get_weather", "arguments": '{"city":"Paris"}'},
                {"type": "function_call_output", "call_id": "call_1", "output": "Sunny"},
                {"type": "reasoning", "id": "rs_1", "summary": []},
                {
                    "type": "message",
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": "Thanks"},
                        {"type": "input_image", "image_url": "https://example.com/a.png"},
                    ],
                },
            ],
            "tools": [{"type": "function", "name": "get_weather", "parameters": {"type": "object"}}],
            "reasoning": {"effort": "high"},
            "max_output_tokens": 50,
        }
    )
    assert parsed.system == "Be helpful." and parsed.reasoning_effort == "high" and parsed.max_tokens == 50
    assert [m["role"] for m in parsed.messages] == ["user", "assistant", "tool", "user"]
    assert len(parsed.messages[3]["content"]) == 2
    rejects(openai_responses.parse_request, {"input": "hi", "previous_response_id": "resp_1"})
    rejects(openai_responses.parse_request, {"input": "hi", "tools": [{"type": "web_search_preview"}]})
    rejects(openai_responses.parse_request, {"input": "hi", "text": {"format": {"type": "json_schema"}}})

    out = encoded(openai_responses.ResponsesStreamEncoder("x:y"))
    events = [frame["event"] for frame in out]
    assert events[0] == "response.created" and events[-1] == "response.completed"
    for expected in (
        "response.output_item.added",
        "response.reasoning_summary_text.delta",
        "response.output_text.delta",
        "response.function_call_arguments.delta",
        "response.function_call_arguments.done",
    ):
        assert expected in events
    assert [frame["data"]["sequence_number"] for frame in out] == list(range(len(out)))
    completed = out[-1]["data"]["response"]
    assert completed["status"] == "completed"
    assert [item["type"] for item in completed["output"]] == ["reasoning", "message", "function_call"]
    assert completed["output"][2]["arguments"] == '{"city":"Paris"}' and completed["output"][2]["call_id"] == "call_1"
    assert completed["usage"]["total_tokens"] == 15

    cut = openai_responses.completion("x:y", [{"type": "text", "text": "Hi"}], USAGE, {"kind": "max-tokens"})
    assert cut["status"] == "incomplete" and cut["incomplete_details"] == {"reason": "max_output_tokens"}


def test_anthropic_messages_parse_and_stream():
    parsed = anthropic_messages.parse_request(
        {
            "model": "x:y",
            "max_tokens": 1024,
            "system": [{"type": "text", "text": "Be brief."}],
            "stop_sequences": ["END"],
            "messages": [
                {"role": "user", "content": "Weather?"},
                {
                    "role": "assistant",
                    "content": [
                        {"type": "thinking", "thinking": "hmm", "signature": "sig"},
                        {"type": "tool_use", "id": "toolu_1", "name": "get_weather", "input": {"city": "Paris"}},
                    ],
                },
                {
                    "role": "user",
                    "content": [
                        {"type": "tool_result", "tool_use_id": "toolu_1", "content": "Sunny", "is_error": False},
                        {"type": "text", "text": "And tomorrow?"},
                        {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": "/9j/"}},
                    ],
                },
            ],
            "tools": [{"name": "get_weather", "description": "Weather", "input_schema": {"type": "object"}}],
        }
    )
    assert parsed.system == "Be brief." and parsed.max_tokens == 1024 and parsed.stop == ["END"]
    assert [m["role"] for m in parsed.messages] == ["user", "assistant", "tool", "user"]
    call = {"type": "tool-call", "id": "toolu_1", "name": "get_weather", "arguments": '{"city":"Paris"}'}
    assert parsed.messages[1]["content"] == [call] and len(parsed.messages[3]["content"]) == 2
    server_tool = {
        "messages": [{"role": "user", "content": "hi"}],
        "tools": [{"type": "web_search_20250305", "name": "s"}],
    }
    rejects(anthropic_messages.parse_request, server_tool)

    out = encoded(anthropic_messages.AnthropicStreamEncoder("x:y"))
    events = [frame["event"] for frame in out]
    assert events[0] == "message_start" and events[-1] == "message_stop"
    starts = [frame["data"] for frame in out if frame["event"] == "content_block_start"]
    assert [(s["index"], s["content_block"]["type"]) for s in starts] == [(0, "thinking"), (1, "text"), (2, "tool_use")]
    assert starts[2]["content_block"]["id"] == "call_1" and events.count("content_block_stop") == 3
    deltas = [frame["data"]["delta"] for frame in out if frame["event"] == "content_block_delta"]
    assert "".join(d["partial_json"] for d in deltas if d["type"] == "input_json_delta") == '{"city":"Paris"}'
    message_delta = next(frame["data"] for frame in out if frame["event"] == "message_delta")
    assert message_delta["delta"]["stop_reason"] == "tool_use" and message_delta["usage"]["output_tokens"] == 5

    blocks = [
        {"type": "text", "text": "Hi"},
        {"type": "tool-call", "id": "call_1", "name": "get_weather", "arguments": '{"city":"Paris"}'},
    ]
    complete = anthropic_messages.message("x:y", blocks, USAGE, {"kind": "tool-calls"})
    assert complete["stop_reason"] == "tool_use"
    assert complete["content"][1] == {
        "type": "tool_use",
        "id": "call_1",
        "name": "get_weather",
        "input": {"city": "Paris"},
    }


def test_stream_encoders_report_upstream_failures():
    chat = frames(openai_chat.ChatStreamEncoder("x:y", False).push(QUOTA))
    assert chat[0]["data"]["error"]["code"] == "QUOTA"
    responses = frames(openai_responses.ResponsesStreamEncoder("x:y").push(QUOTA))
    assert [frame["event"] for frame in responses] == ["response.failed", "error"]
    assert frames(anthropic_messages.AnthropicStreamEncoder("x:y").push(QUOTA))[0]["event"] == "error"


# ---------------------------------------------------------------------- stream normalization
async def test_normalize_langchain_stream():
    async def stream():
        yield AIMessageChunk(content="", additional_kwargs={"reasoning_content": "think"})
        yield AIMessageChunk(content="Hel")
        yield AIMessageChunk(content=[{"type": "text", "text": "lo"}])
        yield AIMessageChunk(content="", tool_call_chunks=[{"index": 0, "id": "call_1", "name": "ping", "args": ""}])
        yield AIMessageChunk(content="", tool_call_chunks=[{"index": 0, "id": None, "name": None, "args": '{"a":'}])
        yield AIMessageChunk(content="", tool_call_chunks=[{"index": 0, "id": None, "name": None, "args": "1}"}])
        yield AIMessageChunk(
            content="",
            response_metadata={"finish_reason": "tool_calls"},
            usage_metadata={
                "input_tokens": 7,
                "output_tokens": 3,
                "total_tokens": 10,
                "input_token_details": {"cache_read": 2},
                "output_token_details": {"reasoning": 1},
            },
        )

    chunks = [chunk async for chunk in normalize(stream())]
    assert [c["type"] for c in chunks] == [
        "block-start",
        "reasoning-delta",
        "block-end",
        "block-start",
        "text-delta",
        "text-delta",
        "block-end",
        "block-start",
        "tool-call-delta",
        "tool-call-delta",
        "tool-call-delta",
        "block-end",
        "usage",
        "finish",
    ]
    assert chunks[8]["name"] == "ping" and "name" not in chunks[9] and chunks[9]["id"] == "call_1"
    assert chunks[-2]["usage"]["cache_read_tokens"] == 2 and chunks[-2]["usage"]["reasoning_tokens"] == 1
    assert chunks[-1]["reason"] == {"kind": "tool-calls"}
    assembler = BlockAssembler()
    for chunk in chunks:
        assembler.push(chunk)
    assert assembler.blocks() == [
        {"type": "reasoning", "text": "think"},
        {"type": "text", "text": "Hello"},
        {"type": "tool-call", "id": "call_1", "name": "ping", "arguments": '{"a":1}'},
    ]

    async def whole():  # a model that does not stream yields one complete message
        yield AIMessage(
            content="done",
            tool_calls=[{"id": "c9", "name": "ping", "args": {"a": 1}}],
            response_metadata={"finish_reason": "length"},
        )

    chunks = [chunk async for chunk in normalize(whole())]
    assert chunks[1] == {"type": "text-delta", "index": 0, "text": "done"}
    assert chunks[4] == {
        "type": "tool-call-delta",
        "index": 1,
        "id": "c9",
        "arguments_delta": '{"a":1}',
        "name": "ping",
    }
    assert chunks[-1]["reason"] == {"kind": "tool-calls"}

    async def cut():
        yield AIMessageChunk(content="par", response_metadata={"stop_reason": "max_tokens"})

    assert [chunk async for chunk in normalize(cut())][-1]["reason"] == {"kind": "max-tokens"}


async def test_backend_overrides_and_upstream_errors():
    calls: list[tuple[str, str, dict[str, Any]]] = []

    class Failing:
        def bind_tools(self, tools: Any) -> Failing:
            return self

        def astream(self, messages: Any, **options: Any) -> Any:
            calls.append(("astream", "", options))
            error = RuntimeError("rate limited")
            error.status_code = 429  # type: ignore[attr-defined]
            raise error

    class Llm:
        def resolve(self, spec: str | None = None, **overrides: Any) -> Any:
            calls.append(("resolve", spec or "", overrides))
            return Failing()

        def build(self, spec: str | None = None, **overrides: Any) -> Any:
            calls.append(("build", spec or "", overrides))
            return Failing()

        def route_type(self, route: str) -> str:
            return "openai" if route == "oa" else "anthropic"

    backend = LangChainBackend(Llm())
    messages = [HumanMessage(content="hi")]
    with pytest.raises(UpstreamError) as info:
        _ = [c async for c in backend.stream(Generation(Target("oa", "m"), messages, stop=["END"]))]
    assert info.value.status == 429 and info.value.code == "upstream_error"
    assert calls[0] == ("resolve", "oa:m", {}) and calls[1][2] == {"stop": ["END"]}
    calls.clear()
    tuned = Generation(Target("oa", "m"), messages, temperature=0.2, max_tokens=9, reasoning_effort="high")
    with pytest.raises(UpstreamError):
        _ = [c async for c in backend.stream(tuned)]
    assert calls[0] == ("build", "oa:m", {"temperature": 0.2, "max_tokens": 9, "reasoning_effort": "high"})
    calls.clear()
    with pytest.raises(UpstreamError):
        _ = [c async for c in backend.stream(Generation(Target("an", "m"), messages, reasoning_effort="high"))]
    assert calls[0] == ("resolve", "an:m", {})


# ---------------------------------------------------------------------- stores
def test_keys(tmp_path):
    path = tmp_path / "keys.json"
    store = KeyStore(path)
    assert store.list() == [] and store.ensure_one("default") is not None and store.ensure_one("default") is None
    created = store.create("cli", ["deepseek:deepseek-chat"])
    key, key_id = created["key"], created["record"]["id"]
    assert key.startswith("pyhg_") and len(key) == 5 + 48 and created["record"]["models"] == ["deepseek:deepseek-chat"]
    assert "key" not in created["record"] and created["record"]["prefix"] == key[:13]
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert store.verify(key)["id"] == key_id and store.verify(key[:-1] + "x") is None and store.verify(None) is None
    store.update(key_id, {"enabled": False})
    assert store.verify(key) is None
    store.update(key_id, {"enabled": True, "models": None, "name": "renamed"})
    assert store.verify(key)["name"] == "renamed" and store.verify(key)["models"] is None
    reloaded = KeyStore(path)
    assert len(reloaded.list()) == 2 and reloaded.reveal(key_id) == key
    reloaded.touch(key_id)
    assert KeyStore(path).list()[1]["lastUsedAt"] is not None
    reloaded.remove(key_id)
    assert len(KeyStore(path).list()) == 1
    for action, code in (
        (lambda: reloaded.remove("nope"), "missing"),
        (lambda: reloaded.create("", None), "invalid"),
        (lambda: reloaded.create("x", ["bad id"]), "invalid"),
    ):
        with pytest.raises(KeyStoreError) as info:
            action()
        assert info.value.code == code
    assert presented_key({"authorization": "Bearer abc"}) == "abc"
    assert presented_key({"x-api-key": " xyz "}) == "xyz"
    assert presented_key({"authorization": "Basic abc"}) is None


def test_usage(tmp_path):
    store = UsageStore(tmp_path / "usage.sqlite")
    now = int(datetime(2026, 11, 9, 12, tzinfo=UTC).timestamp() * 1000)
    base = {
        "keyId": "k1",
        "keyName": "default",
        "protocol": "chat",
        "provider": "deepseek",
        "model": "deepseek-chat",
        "modelId": "deepseek:deepseek-chat",
        "stream": True,
        "cacheReadTokens": 0,
        "cacheWriteTokens": 0,
        "reasoningTokens": 0,
        "ttftMs": 100,
        "durationMs": 500,
        "status": 200,
        "errorCode": None,
    }
    other = {"keyId": "k2", "keyName": "cli", "modelId": "x:y", "provider": "x", "model": "y"}
    store.record({**base, "time": now - 1000, "inputTokens": 1000, "outputTokens": 500})
    failed = {"status": 502, "errorCode": "QUOTA"}
    store.record({**base, **other, **failed, "time": now - 2000, "inputTokens": 2000, "outputTokens": 1000})
    store.record({**base, "time": now - 10 * 24 * 60 * 60_000, "inputTokens": 7, "outputTokens": 7})
    summary = store.summary("7d", {"deepseek:deepseek-chat": {"input": 1, "output": 2}}, now=now)
    totals = summary["totals"]
    assert (totals["requests"], totals["errors"], totals["inputTokens"], totals["outputTokens"]) == (2, 1, 3000, 1500)
    assert totals["cost"] == (1000 * 1 + 500 * 2) / 1_000_000
    by_model = [(g["key"], g["requests"], g["cost"]) for g in summary["byModel"]]
    assert by_model == [("deepseek:deepseek-chat", 1, 0.002), ("x:y", 1, None)]
    assert [(g["label"], g["requests"]) for g in summary["byKey"]] == [("default", 1), ("cli", 1)]
    assert summary["matched"] == 2 and summary["rows"][0]["modelId"] == "deepseek:deepseek-chat"
    assert summary["rows"][0]["stream"] is True and summary["rows"][1]["errorCode"] == "QUOTA"
    assert summary["facets"] == {
        "keys": [{"id": "k2", "name": "cli"}, {"id": "k1", "name": "default"}],
        "models": ["deepseek:deepseek-chat", "x:y"],
        "protocols": ["chat"],
    }
    month = store.summary("30d", {}, now=now)
    assert month["totals"]["requests"] == 3 and month["totals"]["cost"] is None
    errors = store.summary("7d", {}, {"outcome": "error"}, now)
    assert (
        errors["totals"]["requests"] == 1
        and errors["rows"][0]["keyName"] == "cli"
        and len(errors["facets"]["models"]) == 2
    )
    assert store.summary("30d", {}, {"keyId": "k1", "protocol": "chat"}, now)["matched"] == 2
    assert store.summary("30d", {}, {"modelId": "x:y", "outcome": "ok"}, now)["matched"] == 0
    assert parse_filter({"key": "k1", "model": "", "protocol": "bogus", "outcome": "error"}) == {
        "keyId": "k1",
        "outcome": "error",
    }
    today = range_start("today", now)  # local midnight of the day `now` falls on
    assert time.localtime(today / 1000)[:6] == (*time.localtime(now / 1000)[:3], 0, 0, 0)
    assert 0 <= now - today < 25 * 3600 * 1000
    store.close()


def test_settings(tmp_path):
    path = tmp_path / "settings.json"
    store = SettingsStore(path, {"port": 24000})
    assert store.get() == {"enabled": True, "host": "127.0.0.1", "port": 24000, "aliases": {}, "pricing": {}}
    store.save(
        {
            "enabled": False,
            "host": "0.0.0.0",
            "port": 8080,
            "aliases": {"gpt-4o": "deepseek:deepseek-chat"},
            "pricing": {"deepseek:deepseek-chat": {"input": 0.28, "output": 0.42}},
        }
    )
    assert json.loads(path.read_text())["port"] == 8080 and stat.S_IMODE(path.stat().st_mode) == 0o600
    assert SettingsStore(path).get()["aliases"]["gpt-4o"] == "deepseek:deepseek-chat"
    for raw, field in (
        ({"port": 70000}, "port"),
        ({"aliases": {"a": "no-separator"}}, "aliases"),
        ({"pricing": {"x:y": {"input": -1, "output": 0}}}, "pricing"),
        ({"host": "bad host"}, "host"),
        ({"enabled": "yes"}, "enabled"),
    ):
        with pytest.raises(SettingsError) as info:
            store.save(raw)
        assert info.value.field == field
    assert store.get()["port"] == 8080


def test_model_catalog():
    settings = {"aliases": {"gpt-4o": "deepseek:deepseek-chat"}}
    models = [{"id": "deepseek-chat", "name": "DeepSeek Chat"}, {"id": "deepseek-reasoner"}]
    groups = [{"id": "deepseek", "title": "DeepSeek", "models": models}]
    catalog = ModelCatalog(lambda: groups, lambda: ["deepseek", "empty"], lambda: settings)
    listed = catalog.list()
    assert [m["id"] for m in listed] == ["deepseek:deepseek-chat", "deepseek:deepseek-reasoner"]
    assert listed[0]["providerName"] == "DeepSeek" and listed[1]["name"] == "deepseek-reasoner"
    assert catalog.resolve("deepseek:deepseek-chat").model == "deepseek-chat"
    assert catalog.resolve("gpt-4o").id == "deepseek:deepseek-chat"
    assert catalog.resolve("empty:anything").provider == "empty"
    for requested in ("unknown-model", "other:model", None, "", "deepseek:"):
        with pytest.raises(ModelResolutionError):
            catalog.resolve(requested)


async def test_image_resolver():
    png = b"\x89PNG\r\n\x1a\n" + b"0" * 16

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/a.png":
            return httpx.Response(200, content=png, headers={"content-type": "application/octet-stream"})
        if request.url.path == "/text":
            return httpx.Response(200, content=b"hello", headers={"content-type": "text/plain"})
        return httpx.Response(404)

    resolver = ImageResolver(transport=httpx.MockTransport(handler))
    url = await resolver({"source": {"kind": "url", "url": "https://example.com/a.png"}})
    assert url.startswith("data:image/png;base64,") and sniff_media_type(png) == "image/png"
    inline = await resolver({"source": {"kind": "base64", "media_type": "image/jpg", "data": "/9j/\n4AAQ"}})
    assert inline.startswith("data:image/jpeg;base64,")
    for source in (
        {"kind": "url", "url": "https://example.com/text"},
        {"kind": "url", "url": "https://example.com/missing"},
        {"kind": "url", "url": "file:///etc/passwd"},
        {"kind": "base64", "media_type": "image/tiff", "data": "AAAA"},
        {"kind": "base64", "media_type": "image/png", "data": "***"},
    ):
        with pytest.raises(GatewayError):
            await resolver({"source": source})
    with pytest.raises(GatewayError, match="exceeds"):
        await ImageResolver(max_bytes=4)({"source": {"kind": "base64", "media_type": "image/png", "data": "AAAAAAAA"}})


# ---------------------------------------------------------------------- application
async def echo(generation: Generation) -> Any:
    """Streams the model name and the last message's text back, one tool call when a tool is declared, then usage."""
    text = generation.messages[-1].text
    yield {"type": "block-start", "index": 0, "block_type": "text"}
    for part in (f"{generation.target.model}:", text):
        yield {"type": "text-delta", "index": 0, "text": part}
        await asyncio.sleep(0.005)
    yield {"type": "block-end", "index": 0}
    if generation.tools:
        name = generation.tools[0]["function"]["name"]
        yield {"type": "block-start", "index": 1, "block_type": "tool-call"}
        yield {"type": "tool-call-delta", "index": 1, "id": "call_echo", "name": name, "arguments_delta": "{}"}
        yield {"type": "block-end", "index": 1}
    yield {"type": "usage", "usage": {"input_tokens": 3, "output_tokens": 2}}
    yield {"type": "finish", "reason": {"kind": "tool-calls" if generation.tools else "stop"}}


async def failing(generation: Generation) -> Any:
    raise UpstreamError(429, "QUOTA", "quota exceeded")
    yield  # pragma: no cover


async def test_gateway_application(tmp_path):
    keys = KeyStore(tmp_path / "keys.json")
    usage = UsageStore(tmp_path / "usage.sqlite")
    full = keys.create("full", None)["key"]
    limited = keys.create("limited", ["echo:fast"])["key"]
    settings = {"aliases": {"gpt-4o": "echo:fast"}}
    groups = [
        {"id": "echo", "title": "Echo", "models": [{"id": "fast", "name": "Fast"}, {"id": "slow", "name": "Slow"}]}
    ]
    catalog = ModelCatalog(lambda: groups, lambda: ["echo"], lambda: settings)
    backend = {"generate": echo}

    def relay(generation: Generation) -> Any:
        return backend["generate"](generation)

    deps = GatewayDeps(
        generate=relay,
        catalog=catalog,
        keys=keys,
        usage=usage,
        load_image=no_images,
        max_body_bytes=4096,
        logger=logging.getLogger("test.gateway"),
    )
    transport = httpx.ASGITransport(app=create_app(deps))
    async with httpx.AsyncClient(transport=transport, base_url="http://gateway") as client:

        async def post(path: str, body: Any, key: str = full, **headers: str) -> httpx.Response:
            return await client.post(path, json=body, headers={"authorization": f"Bearer {key}", **headers})

        # authentication, unknown routes, CORS preflight
        assert (await client.get("/v1/models")).status_code == 401
        denied = await client.get("/v1/models", headers={"authorization": "Bearer nope"})
        assert denied.status_code == 401 and denied.json()["error"]["code"] == "invalid_api_key"
        assert denied.headers["www-authenticate"] == "Bearer"
        anthropic = {"x-api-key": "nope", "anthropic-version": "2023-06-01"}
        unauthorized = await client.post("/v1/messages", content="{}", headers=anthropic)
        assert unauthorized.status_code == 401 and unauthorized.json()["type"] == "error"
        assert (await client.get("/v1/unknown", headers={"authorization": f"Bearer {full}"})).status_code == 404
        preflight = await client.options("/v1/models")
        assert preflight.status_code == 204 and preflight.headers["access-control-allow-origin"] == "*"
        assert (
            await client.get("/v1/chat/completions", headers={"authorization": f"Bearer {full}"})
        ).status_code == 405

        # model listing per key, in both shapes
        listed = (await client.get("/v1/models", headers={"authorization": f"Bearer {full}"})).json()
        assert [m["id"] for m in listed["data"]] == ["echo:fast", "echo:slow"] and listed["object"] == "list"
        narrow = (
            await client.get("/v1/models", headers={"x-api-key": limited, "anthropic-version": "2023-06-01"})
        ).json()
        assert [(m["id"], m["type"]) for m in narrow["data"]] == [("echo:fast", "model")] and narrow[
            "first_id"
        ] == "echo:fast"

        # chat completions: an alias, then a stream with usage and a tool call
        chat = await post("/v1/chat/completions", {"model": "gpt-4o", "messages": [{"role": "user", "content": "hi"}]})
        assert chat.status_code == 200 and chat.json()["model"] == "echo:fast"
        assert (
            chat.json()["choices"][0]["message"]["content"] == "fast:hi" and chat.json()["usage"]["total_tokens"] == 5
        )
        stream = await post(
            "/v1/chat/completions",
            {
                "model": "echo:slow",
                "stream": True,
                "stream_options": {"include_usage": True},
                "messages": [{"role": "user", "content": "yo"}],
                "tools": [{"type": "function", "function": {"name": "ping", "parameters": {}}}],
            },
        )
        assert stream.status_code == 200 and stream.headers["content-type"].startswith("text/event-stream")
        chunks = frames(stream.text)
        assert chunks[-1]["data"] == "[DONE]"
        data = [frame["data"] for frame in chunks[:-1]]
        assert "".join(d["choices"][0]["delta"].get("content", "") for d in data if d["choices"]) == "slow:yo"
        assert any(d["choices"] and d["choices"][0]["delta"].get("tool_calls") for d in data)
        assert any(d["choices"] and d["choices"][0]["finish_reason"] == "tool_calls" for d in data)
        assert data[-1]["usage"]["total_tokens"] == 5

        # key allowlist, unsupported parameter, malformed and oversized bodies, a missing model
        message = {"role": "user", "content": "x"}
        blocked = await post("/v1/chat/completions", {"model": "echo:slow", "messages": [message]}, limited)
        assert blocked.status_code == 403 and blocked.json()["error"]["code"] == "model_not_allowed"
        assert (
            await post("/v1/chat/completions", {"model": "echo:fast", "n": 3, "messages": [message]})
        ).status_code == 400
        auth = {"authorization": f"Bearer {full}"}
        assert (await client.post("/v1/chat/completions", content="{oops", headers=auth)).status_code == 400
        big = {"model": "echo:fast", "messages": [{"role": "user", "content": "x" * 5000}]}
        assert (await post("/v1/chat/completions", big)).status_code == 413
        nameless = await post("/v1/chat/completions", {"messages": [message]})
        assert nameless.status_code == 404 and nameless.json()["error"]["code"] == "model_not_found"

        # responses
        events = [
            f["event"]
            for f in frames((await post("/v1/responses", {"model": "echo:fast", "stream": True, "input": "ping"})).text)
        ]
        assert events[0] == "response.created" and events[-1] == "response.completed"
        item = {"role": "user", "content": [{"type": "input_text", "text": "pong"}]}
        answered = (await post("/v1/responses", {"model": "echo:fast", "input": [item]})).json()
        assert answered["output"][0]["content"][0]["text"] == "fast:pong" and answered["status"] == "completed"

        # anthropic messages
        hey = {"model": "echo:fast", "max_tokens": 10, "messages": [{"role": "user", "content": "hey"}]}
        streamed = await post("/v1/messages", {**hey, "stream": True}, **{"anthropic-version": "2023-06-01"})
        events = [frame["event"] for frame in frames(streamed.text)]
        assert events[0] == "message_start" and events[-1] == "message_stop"
        whole = (await post("/v1/messages", hey)).json()
        assert whole["content"][0]["text"] == "fast:hey" and whole["stop_reason"] == "end_turn"
        assert whole["usage"]["input_tokens"] == 3
        forbidden = await post("/v1/messages", {**hey, "model": "echo:slow"}, limited)
        assert forbidden.status_code == 403 and forbidden.json()["error"]["type"] == "permission_error"

        # a route failure surfaces with the provider status; after a stream started, as an error frame
        backend["generate"] = failing
        quota = await post("/v1/chat/completions", {"model": "echo:fast", "messages": [message]})
        assert quota.status_code == 429 and quota.json()["error"]["code"] == "QUOTA"
        late = await post("/v1/messages", {**hey, "max_tokens": 5, "stream": True})
        assert late.status_code == 200 and frames(late.text)[-1]["event"] == "error"
        backend["generate"] = echo

    # ledger: every authenticated protocol request is one row
    summary = usage.summary("today", {})
    assert summary["totals"]["requests"] == 14 and summary["totals"]["errors"] == 8
    assert next(g for g in summary["byKey"] if g["label"] == "limited")["requests"] == 2
    assert any(row["status"] == 429 and row["errorCode"] == "QUOTA" and not row["stream"] for row in summary["rows"])
    assert any(row["status"] == 429 and row["protocol"] == "messages" and row["stream"] for row in summary["rows"])
    assert any(
        row["status"] == 200 and row["ttftMs"] is not None and row["inputTokens"] == 3 for row in summary["rows"]
    )
    assert next(key for key in keys.list() if key["name"] == "full")["lastUsedAt"] is not None
    usage.close()


async def test_listener(tmp_path):
    async def app(scope: Any, receive: Any, send: Any) -> None:
        await send({"type": "http.response.start", "status": 204, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    listener = Listener(app, logging.getLogger("test.gateway"))
    await listener.apply(True, "127.0.0.1", 0)
    port = listener.listening["port"]
    assert listener.error is None and port > 0
    async with httpx.AsyncClient() as client:
        assert (await client.get(f"http://127.0.0.1:{port}/")).status_code == 204
    other = Listener(app, logging.getLogger("test.gateway"))
    await other.apply(True, "127.0.0.1", port)
    assert other.listening is None and other.error
    await listener.apply(False, "127.0.0.1", port)
    assert listener.listening is None and listener.error is None
    await other.apply(True, "127.0.0.1", port)
    assert other.listening == {"host": "127.0.0.1", "port": port}
    await other.close()
    assert other.listening is None


# ---------------------------------------------------------------------- harness
async def test_gateway_in_the_harness(home, tmp_path):
    profile = Profile.init("web", home=str(home))
    route = {"type": "echo", "title": "Echo", "models": [{"id": "echo", "name": "Echo"}]}
    patch = [
        HTTP_OFF,
        {"id": "llm", "config": {"providers": {"local": route}}, "merge": True},
        {"id": "gateway", "config": {"listen": False, "data_dir": str(tmp_path / "gateway")}, "merge": True},
    ]
    async with Harness(profile, patch=patch) as h:
        gateway = h.get("gateway")
        management = httpx.ASGITransport(app=h.get("http").app)
        async with httpx.AsyncClient(transport=management, base_url="http://t") as c:
            status = (await c.get("/api/gateway/status")).json()
            assert status["settings"] == {
                "enabled": False,
                "host": "127.0.0.1",
                "port": 8766,
                "aliases": {},
                "pricing": {},
            }
            assert status["listening"] is None and status["listenError"] is None
            assert {
                "id": "local:echo",
                "provider": "local",
                "providerName": "Echo",
                "model": "echo",
                "name": "Echo",
            } in status["models"]
            assert [key["name"] for key in status["keys"]] == ["default"]
            default_id = status["keys"][0]["id"]
            default_key = (await c.get("/api/gateway/keys", params={"id": default_id})).json()["key"]
            assert (
                default_key.startswith("pyhg_")
                and (await c.get("/api/gateway/keys", params={"id": "x"})).status_code == 404
            )

            created = (await c.post("/api/gateway/keys", json={"name": "cli", "models": ["local:echo"]})).json()
            assert created["record"]["models"] == ["local:echo"] and created["key"].startswith("pyhg_")
            patched = await c.patch("/api/gateway/keys", json={"id": created["record"]["id"], "enabled": False})
            assert patched.json()["record"]["enabled"] is False
            assert (await c.post("/api/gateway/keys", json={"name": ""})).status_code == 400
            assert (await c.patch("/api/gateway/keys", json={"id": "nope", "name": "x"})).status_code == 404
            remaining = (await c.delete("/api/gateway/keys", params={"id": created["record"]["id"]})).json()
            assert [key["name"] for key in remaining["keys"]] == ["default"]

            aliases = {"gpt-4o": "local:echo"}
            saved = await c.put("/api/gateway/settings", json={**status["settings"], "aliases": aliases})
            assert saved.status_code == 200 and saved.json()["settings"]["aliases"] == aliases
            assert (await c.put("/api/gateway/settings", json={**status["settings"], "port": 0})).status_code == 400

            # a request through the gateway application reaches the echo route of ctx.llm
            protocol = httpx.ASGITransport(app=gateway.app)
            async with httpx.AsyncClient(transport=protocol, base_url="http://gateway") as g:
                auth = {"authorization": f"Bearer {default_key}"}
                listed = (await g.get("/v1/models", headers=auth)).json()
                assert "local:echo" in [m["id"] for m in listed["data"]]
                body = {"model": "gpt-4o", "messages": [{"role": "user", "content": "ping"}]}
                reply = await g.post("/v1/chat/completions", json=body, headers=auth)
                assert reply.status_code == 200 and reply.json()["choices"][0]["message"]["content"].startswith(
                    "echo: ping"
                )
                streamed = await g.post("/v1/messages", json={**body, "max_tokens": 16, "stream": True}, headers=auth)
                events = [frame["event"] for frame in frames(streamed.text)]
                assert events[0] == "message_start" and "content_block_delta" in events and events[-1] == "message_stop"

            usage = (await c.get("/api/gateway/usage", params={"range": "today", "protocol": "messages"})).json()
            assert (
                usage["matched"] == 1
                and usage["rows"][0]["modelId"] == "local:echo"
                and usage["rows"][0]["stream"] is True
            )
            assert usage["facets"]["protocols"] == ["chat", "messages"]
            assert (await c.get("/api/gateway/usage", params={"range": "year"})).status_code == 400
    assert (tmp_path / "gateway" / "keys.json").exists() and (tmp_path / "gateway" / "usage.sqlite").exists()
