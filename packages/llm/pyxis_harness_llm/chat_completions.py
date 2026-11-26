from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from functools import cache
from typing import Any

from langchain_core.messages import AIMessage
from langchain_core.messages.ai import UsageMetadata, add_usage, subtract_usage

# Where a Chat Completions service puts the model's reasoning text; the first field that holds text is read.
REASONING_FIELDS = ("reasoning_content", "reasoning", "reasoning_text")
KINDS = ("openai", "deepseek")


def reasoning_of(fields: Any) -> str | None:
    """Reasoning text of a delta or message of a Chat Completions response; ``None`` without one."""
    if not isinstance(fields, dict):
        fields = {**getattr(fields, "__dict__", {}), **(getattr(fields, "model_extra", None) or {})}
    for name in REASONING_FIELDS:
        value = fields.get(name)
        if isinstance(value, str) and value:
            return value
    return None


def cache_read_of(usage: Any) -> int | None:
    """Prompt tokens read from cache, wherever the service reports them; ``None`` when it does not."""
    if not isinstance(usage, dict):
        return None
    for value in (
        (usage.get("prompt_tokens_details") or {}).get("cached_tokens"),
        usage.get("prompt_cache_hit_tokens"),
        usage.get("cached_tokens"),
    ):
        if isinstance(value, int):
            return value
    return None


def with_cache_read(usage: UsageMetadata | None, raw: Any) -> UsageMetadata | None:
    """``usage`` with ``input_token_details.cache_read`` taken from ``raw`` when the model class left it out."""
    cached = cache_read_of(raw)
    if not usage or cached is None or (usage.get("input_token_details") or {}).get("cache_read") is not None:
        return usage
    return {**usage, "input_token_details": {**(usage.get("input_token_details") or {}), "cache_read": cached}}


class RunningUsage:
    """
    Usage of one streamed response as increments.

    A service reports usage once at the end (OpenAI) or as a running total on every chunk. Chunks are merged by
    adding their usage, so each report becomes its increment over the reports before it: the sum is the latest
    report.
    """

    def __init__(self) -> None:
        self.reported: UsageMetadata | None = None

    def increment(self, usage: UsageMetadata) -> UsageMetadata:
        delta = subtract_usage(usage, self.reported)
        self.reported = add_usage(self.reported, delta)
        return delta

    def apply(self, chunk: Any) -> Any:
        message = getattr(chunk, "message", None)
        if isinstance(message, AIMessage) and message.usage_metadata:
            message.usage_metadata = self.increment(message.usage_metadata)
        return chunk


class ChatCompletions:
    """
    Mixin over ``BaseChatOpenAI`` for services that speak Chat Completions their own way.

    | part      | contract                                                                             |
    |-----------|--------------------------------------------------------------------------------------|
    | usage     | the latest report of a stream counts, not the sum of every chunk's report            |
    |           | ``choices[0].usage`` is read when the chunk carries no ``usage``                     |
    |           | cache reads: ``prompt_tokens_details.cached_tokens``, ``prompt_cache_hit_tokens``    |
    |           | or ``cached_tokens``                                                                 |
    | reasoning | the first of ``REASONING_FIELDS`` with text → ``additional_kwargs.reasoning_content``|
    """

    def _stream(self, *args: Any, **kwargs: Any) -> Iterator[Any]:
        usage = RunningUsage()
        for chunk in super()._stream(*args, **kwargs):  # type: ignore[misc]
            yield usage.apply(chunk)

    async def _astream(self, *args: Any, **kwargs: Any) -> AsyncIterator[Any]:
        usage = RunningUsage()
        async for chunk in super()._astream(*args, **kwargs):  # type: ignore[misc]
            yield usage.apply(chunk)

    def _convert_chunk_to_generation_chunk(
        self, chunk: dict, default_chunk_class: type, base_generation_info: dict | None
    ) -> Any:
        choices = chunk.get("choices") or chunk.get("chunk", {}).get("choices") or []
        choice = choices[0] if choices and isinstance(choices[0], dict) else {}
        if not chunk.get("usage") and isinstance(choice.get("usage"), dict):
            chunk = {**chunk, "usage": choice["usage"]}
        generation = super()._convert_chunk_to_generation_chunk(  # type: ignore[misc]
            chunk, default_chunk_class, base_generation_info
        )
        message = getattr(generation, "message", None)
        if not isinstance(message, AIMessage):
            return generation
        message.usage_metadata = with_cache_read(message.usage_metadata, chunk.get("usage"))
        reasoning = reasoning_of(choice.get("delta") or {})
        if reasoning and not message.additional_kwargs.get("reasoning_content"):
            message.additional_kwargs["reasoning_content"] = reasoning
        return generation

    def _create_chat_result(self, response: Any, generation_info: dict | None = None) -> Any:
        result = super()._create_chat_result(response, generation_info)  # type: ignore[misc]
        data = response if isinstance(response, dict) else response.model_dump()
        choices = data.get("choices") or []
        for generation, choice in zip(result.generations, choices, strict=False):
            message = generation.message
            if not isinstance(message, AIMessage):
                continue
            message.usage_metadata = with_cache_read(message.usage_metadata, data.get("usage"))
            reasoning = reasoning_of(choice.get("message") or {})
            if reasoning and not message.additional_kwargs.get("reasoning_content"):
                message.additional_kwargs["reasoning_content"] = reasoning
        return result


@cache
def model_class(kind: str) -> type:
    """The chat model class of ``kind`` (one of ``KINDS``) with :class:`ChatCompletions` mixed in."""
    if kind == "openai":
        from langchain_openai import ChatOpenAI as Base  # noqa: PLC0415 - an optional provider package
    elif kind == "deepseek":
        from langchain_deepseek import ChatDeepSeek as Base  # noqa: PLC0415 - an optional provider package
    else:
        raise ValueError(f"no Chat Completions model class for {kind!r}; one of {', '.join(KINDS)}")
    return type(Base.__name__, (ChatCompletions, Base), {"__module__": __name__})
