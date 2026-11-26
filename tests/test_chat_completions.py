"""Chat Completions routes: the usage of a stream is its latest report; reasoning text is read where services put it."""

from __future__ import annotations

import json

import httpx
import pytest

from pyxis_harness import Harness, Profile
from pyxis_harness_compaction.checkpoint import measure
from pyxis_harness_llm.chat_completions import RunningUsage, cache_read_of, model_class, reasoning_of


def chunk(delta=None, usage=None, finish=None, choice_usage=None):
    choices = [] if delta is None else [{"index": 0, "delta": delta, "finish_reason": finish}]
    if choice_usage:
        choices[0]["usage"] = choice_usage
    out = {"id": "c1", "object": "chat.completion.chunk", "created": 1, "model": "m", "choices": choices}
    return {**out, "usage": usage} if usage else out


def usage(prompt, completion, **more):
    return {"prompt_tokens": prompt, "completion_tokens": completion, "total_tokens": prompt + completion, **more}


def service(chunks=None, message=None, final_usage=None):
    """A transport that answers a stream request with ``chunks`` and a plain one with ``message``."""
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        requests.append(body)
        if body.get("stream"):
            text = "".join(f"data: {json.dumps(c)}\n\n" for c in chunks) + "data: [DONE]\n\n"
            return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=text)
        choice = {"index": 0, "message": {"role": "assistant", **message}, "finish_reason": "stop"}
        result = {"id": "c1", "object": "chat.completion", "created": 1, "model": "m", "choices": [choice]}
        return httpx.Response(200, json={**result, "usage": final_usage})

    return httpx.MockTransport(handler), requests


async def streamed(model):
    full = None
    async for part in model.astream("hi"):
        full = part if full is None else full + part
    return full


@pytest.fixture
def profile(home):
    return Profile.init("web", home=str(home))


def route(**options):
    providers = {"compat": {"type": "openai", "base_url": "http://compat.test/v1", "api_key": "k", **options}}
    return [
        {"id": "llm", "config": {"default": "echo:echo", "providers": providers}},
        {"id": "http", "config": {"serve": False}},
    ]


async def test_a_running_total_on_every_chunk_counts_once(profile):
    words = ["你", "好", "。"]
    chunks = [
        chunk({"role": "assistant", "content": ""}, usage(12000, 0)),
        *(chunk({"reasoning_content": w}, usage(12000, i + 1)) for i, w in enumerate(["先", "想"])),
        *(chunk({"content": w}, usage(12000, 3 + i)) for i, w in enumerate(words)),
        chunk({}, usage(12000, 6, prompt_tokens_details={"cached_tokens": 9000}), finish="stop"),
    ]
    transport, requests = service(chunks)
    async with Harness(profile, patch=route()) as h:
        model = h.get("llm").resolve("compat:m", http_async_client=httpx.AsyncClient(transport=transport))
        message = await streamed(model)
    assert message.content == "你好。" and message.additional_kwargs["reasoning_content"] == "先想"
    assert (message.usage_metadata["input_tokens"], message.usage_metadata["output_tokens"]) == (12000, 6)
    assert message.usage_metadata["input_token_details"]["cache_read"] == 9000
    assert measure([message]) == 12006  # what compaction compares with the context window
    assert requests[0]["stream_options"] == {"include_usage": True}


async def test_one_report_at_the_end_and_cache_fields_of_other_services(profile):
    chunks = [
        chunk({"role": "assistant", "content": "ok"}),
        chunk({}, finish="stop"),
        chunk(usage=usage(800, 2, prompt_cache_hit_tokens=600)),
    ]
    transport, _ = service(chunks)
    moonshot = [chunk({"role": "assistant", "content": "ok"}), chunk({}, finish="stop", choice_usage=usage(70, 3))]
    in_choice, _ = service(moonshot)
    async with Harness(profile, patch=route()) as h:
        llm = h.get("llm")
        message = await streamed(llm.resolve("compat:m", http_async_client=httpx.AsyncClient(transport=transport)))
        assert message.usage_metadata["input_tokens"] == 800 and message.usage_metadata["output_tokens"] == 2
        assert message.usage_metadata["input_token_details"]["cache_read"] == 600
        other = await streamed(llm.resolve("compat:n", http_async_client=httpx.AsyncClient(transport=in_choice)))
        assert (other.usage_metadata["input_tokens"], other.usage_metadata["output_tokens"]) == (70, 3)


async def test_plain_responses_and_the_route_option(profile):
    transport, requests = service(
        chunks=[chunk({"role": "assistant", "content": "ok"}), chunk({}, finish="stop")],
        message={"content": "答", "reasoning": "想"},
        final_usage=usage(50, 4, cached_tokens=30),
    )
    async with Harness(profile, patch=route(stream_usage=False)) as h:
        model = h.get("llm").resolve("compat:m", http_async_client=httpx.AsyncClient(transport=transport))
        message = await model.ainvoke("hi")
        assert message.content == "答" and message.additional_kwargs["reasoning_content"] == "想"
        assert message.usage_metadata["input_token_details"]["cache_read"] == 30
        await streamed(model)
    assert "stream_options" not in requests[-1]  # the route turned the request for stream usage off


def test_the_parts():
    assert reasoning_of({"reasoning_content": "", "reasoning": "b", "reasoning_text": "c"}) == "b"
    assert reasoning_of({"content": "x"}) is None and reasoning_of({"reasoning": None}) is None
    assert cache_read_of({"prompt_tokens_details": {"cached_tokens": 1}, "cached_tokens": 9}) == 1
    assert cache_read_of({"prompt_cache_hit_tokens": 2}) == 2 and cache_read_of({"prompt_tokens": 5}) is None
    running = RunningUsage()
    reports = [(100, 0), (100, 4), (100, 9)]
    increments = [running.increment({"input_tokens": i, "output_tokens": o, "total_tokens": i + o}) for i, o in reports]
    assert [(u["input_tokens"], u["output_tokens"]) for u in increments] == [(100, 0), (0, 4), (0, 5)]
    assert {model_class(kind).__name__ for kind in ("openai", "deepseek")} == {"ChatOpenAI", "ChatDeepSeek"}
    with pytest.raises(ValueError, match="no Chat Completions model class"):
        model_class("anthropic")


def test_the_synchronous_stream_counts_the_same():
    chunks = [
        chunk({"role": "assistant", "content": "a"}, usage(40, 1)),
        chunk({"content": "b"}, usage(40, 2)),
        chunk({}, usage(40, 2), finish="stop"),
    ]
    transport, _ = service(chunks)
    model = model_class("deepseek")(
        model="m", api_key="k", api_base="http://compat.test/v1", http_client=httpx.Client(transport=transport)
    )
    full = None
    for part in model.stream("hi"):
        full = part if full is None else full + part
    assert full.content == "ab" and (full.usage_metadata["input_tokens"], full.usage_metadata["output_tokens"]) == (
        40,
        2,
    )
