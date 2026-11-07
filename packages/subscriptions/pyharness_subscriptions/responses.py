"""OpenAI Responses wire format shared by Codex, ChatGPT and Grok: LangChain messages → ``input`` items, tool
definitions, and the streaming translation of Responses SSE events into ``AIMessageChunk`` (text, reasoning,
tool calls, usage)."""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import AsyncIterator, Iterator
from typing import Any

import httpx
from langchain_core.callbacks import AsyncCallbackManagerForLLMRun, CallbackManagerForLLMRun
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult
from langchain_core.utils.function_calling import convert_to_openai_tool
from langgraph.config import get_config
from pydantic import ConfigDict, Field

from pyharness import package_prompts

from .common import LlmError, http_error, iter_sse, read_error

PROMPTS = package_prompts(__file__)
UNKNOWN_OUTCOME: str = PROMPTS["responses"]["UNKNOWN_OUTCOME"]


# ---------------------------------------------------------------------- input building
def _text_of(content: Any) -> str:
    if isinstance(content, str):
        return content
    parts = []
    for block in content or []:
        if isinstance(block, str):
            parts.append(block)
        elif isinstance(block, dict) and block.get("type") in ("text", None) and block.get("text"):
            parts.append(str(block["text"]))
    return "".join(parts)


def _images_of(content: Any) -> list[str]:
    out = []
    for block in content if isinstance(content, list) else []:
        if not isinstance(block, dict):
            continue
        if block.get("type") == "image_url":
            url = block.get("image_url")
            url = url.get("url") if isinstance(url, dict) else url
            if url:
                out.append(str(url))
        elif block.get("type") == "image":
            if block.get("url"):
                out.append(str(block["url"]))
            elif block.get("data") and block.get("mime_type"):
                out.append(f"data:{block['mime_type']};base64,{block['data']}")
    return out


def short_call_id(call_id: str) -> str:
    if len(call_id) <= 64:
        return call_id
    return "call_" + hashlib.sha256(call_id.encode()).hexdigest()[:59]


def to_responses_input(
    messages: list[BaseMessage], *, repair: bool = True, shorten_ids: bool = False, namespace: str | None = None
) -> tuple[str | None, list[dict[str, Any]]]:
    """``(instructions, input)``: system messages become the instructions; tool calls / results become
    ``function_call`` / ``function_call_output`` items; calls without an output get a placeholder output."""
    instructions: list[str] = []
    items: list[dict[str, Any]] = []
    ids: dict[str, str] = {}
    for message in messages:
        if isinstance(message, SystemMessage):
            instructions.append(_text_of(message.content))
        elif isinstance(message, HumanMessage):
            content: list[dict[str, Any]] = []
            text = _text_of(message.content)
            if text:
                content.append({"type": "input_text", "text": text})
            content.extend({"type": "input_image", "image_url": url} for url in _images_of(message.content))
            if content:
                items.append({"type": "message", "role": "user", "content": content})
        elif isinstance(message, AIMessage):
            text = _text_of(message.content)
            if text:
                items.append(
                    {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": text}]}
                )
            for call in message.tool_calls or []:
                cid = str(call.get("id") or "")
                wire = short_call_id(cid) if shorten_ids else cid
                ids[cid] = wire
                item: dict[str, Any] = {
                    "type": "function_call",
                    "call_id": wire,
                    "name": call.get("name"),
                    "arguments": json.dumps(call.get("args") or {}, ensure_ascii=False),
                }
                if namespace:
                    item["namespace"] = namespace
                items.append(item)
        elif isinstance(message, ToolMessage):
            cid = str(message.tool_call_id or "")
            wire = ids.get(cid, short_call_id(cid) if shorten_ids else cid)
            items.append({"type": "function_call_output", "call_id": wire, "output": _text_of(message.content) or ""})
    if repair:
        outputs = {it["call_id"] for it in items if it.get("type") == "function_call_output"}
        calls = {it["call_id"] for it in items if it.get("type") == "function_call"}
        repaired: list[dict[str, Any]] = []
        for it in items:
            if it.get("type") == "function_call_output" and it["call_id"] not in calls:
                continue  # orphan output
            repaired.append(it)
            if it.get("type") == "function_call" and it["call_id"] not in outputs:
                repaired.append({"type": "function_call_output", "call_id": it["call_id"], "output": UNKNOWN_OUTCOME})
        items = repaired
    return ("\n\n".join(i for i in instructions if i) or None), items


def to_responses_tools(tools: list[Any], *, strict: bool | None = False) -> list[dict[str, Any]]:
    out = []
    for tool in tools:
        spec = convert_to_openai_tool(tool)["function"]
        item: dict[str, Any] = {
            "type": "function",
            "name": spec["name"],
            "description": spec.get("description") or "",
            "parameters": spec.get("parameters") or {"type": "object", "properties": {}},
        }
        if strict is not None:
            item["strict"] = strict
        out.append(item)
    return out


# ---------------------------------------------------------------------- streaming translation
class ResponsesTranslator:
    """Turns Responses SSE events into chunks; keeps per-item state for tool calls."""

    def __init__(self, label: str) -> None:
        self.label = label
        self.calls: dict[str, dict[str, Any]] = {}  # item_id -> {index, call_id, name, args}
        self.call_index = 0
        self.saw_content = False
        self.saw_call = False
        self.completed = False

    def feed(self, event: str | None, data: str) -> Iterator[AIMessageChunk]:
        if data == "[DONE]":
            return
        try:
            payload = json.loads(data)
        except ValueError:
            return
        kind = payload.get("type") or event or ""
        if kind == "response.output_item.added":
            item = payload.get("item") or {}
            if item.get("type") == "function_call":
                self.saw_call = True
                idx = self.call_index
                self.call_index += 1
                self.calls[item.get("id") or f"item{idx}"] = {
                    "index": idx,
                    "call_id": item.get("call_id") or item.get("id"),
                    "name": item.get("name") or "",
                    "args": "",
                }
                yield AIMessageChunk(
                    content="",
                    tool_call_chunks=[
                        {
                            "name": item.get("name") or "",
                            "args": "",
                            "id": item.get("call_id") or item.get("id"),
                            "index": idx,
                            "type": "tool_call_chunk",
                        }
                    ],
                )
        elif kind == "response.output_text.delta":
            delta = str(payload.get("delta") or "")
            if delta:
                self.saw_content = True
                yield AIMessageChunk(content=delta)
        elif kind in ("response.reasoning_summary_text.delta", "response.reasoning_text.delta"):
            delta = str(payload.get("delta") or "")
            if delta:
                self.saw_content = True
                yield AIMessageChunk(content="", additional_kwargs={"reasoning_content": delta})
        elif kind == "response.function_call_arguments.delta":
            state = self.calls.get(payload.get("item_id") or "")
            if state is not None:
                delta = str(payload.get("delta") or "")
                state["args"] += delta
                yield AIMessageChunk(
                    content="",
                    tool_call_chunks=[
                        {"name": None, "args": delta, "id": None, "index": state["index"], "type": "tool_call_chunk"}
                    ],
                )
        elif kind == "response.output_item.done":
            item = payload.get("item") or {}
            if item.get("type") == "function_call":
                state = self.calls.get(item.get("id") or "")
                if state is not None and not state["args"] and item.get("arguments"):
                    state["args"] = str(item["arguments"])
                    yield AIMessageChunk(
                        content="",
                        tool_call_chunks=[
                            {
                                "name": None,
                                "args": str(item["arguments"]),
                                "id": None,
                                "index": state["index"],
                                "type": "tool_call_chunk",
                            }
                        ],
                    )
            elif item.get("type") == "message" and not self.saw_content:
                text = "".join(
                    str(c.get("text") or "")
                    for c in item.get("content") or []
                    if isinstance(c, dict) and c.get("type") == "output_text"
                )
                if text:
                    self.saw_content = True
                    yield AIMessageChunk(content=text)
        elif kind == "response.completed":
            self.completed = True
            usage = (payload.get("response") or {}).get("usage") or {}
            cached = int(((usage.get("input_tokens_details") or {}).get("cached_tokens")) or 0)
            inp = int(usage.get("input_tokens") or 0)
            out = int(usage.get("output_tokens") or 0)
            reasoning = int(((usage.get("output_tokens_details") or {}).get("reasoning_tokens")) or 0)
            meta: dict[str, Any] = {"input_tokens": inp, "output_tokens": out, "total_tokens": inp + out}
            if cached:
                meta["input_token_details"] = {"cache_read": cached}
            if reasoning:
                meta["output_token_details"] = {"reasoning": reasoning}
            finish = "tool_calls" if self.saw_call else "stop"
            yield AIMessageChunk(
                content="",
                response_metadata={"finish_reason": finish, "model_name": (payload.get("response") or {}).get("model")},
                usage_metadata=meta,
            )
            if not self.saw_content and not self.saw_call:
                raise LlmError("EMPTY_RESPONSE", f"{self.label} returned no content")
        elif kind in ("response.failed", "response.incomplete", "error"):
            err = (
                payload.get("error")
                or (payload.get("response") or {}).get("error")
                or (payload.get("response") or {}).get("incomplete_details")
                or {}
            )
            code = str(err.get("code") or err.get("reason") or "")
            message = str(err.get("message") or code or kind)
            if "context_window_exceeded" in code or "context" in code:
                raise LlmError("CONTEXT_WINDOW_EXCEEDED", message)
            if "insufficient" in code or "quota" in code:
                raise LlmError("QUOTA_EXCEEDED", message)
            raise LlmError("SERVER", f"{self.label}: {message}")


# ---------------------------------------------------------------------- chat model
class ResponsesChatModel(BaseChatModel):
    """A LangChain chat model over a Responses-style streaming endpoint. Subclasses provide the request."""

    model_name: str
    label: str = "responses"
    provider_ref: Any = None  # the provider object (headers, endpoint, token manager)
    account_key: str | None = None
    session_id_hint: str | None = None
    reasoning_effort: str | None = None
    max_tokens: int | None = None
    bound_tools: list[Any] = Field(default_factory=list)
    stream_idle_timeout: float = 300.0

    model_config = ConfigDict(arbitrary_types_allowed=True)

    @property
    def _llm_type(self) -> str:
        return f"pyharness-subscriptions-{self.label}"

    @property
    def _identifying_params(self) -> dict[str, Any]:
        return {"model": self.model_name, "label": self.label}

    def bind_tools(self, tools: Any, **kwargs: Any) -> ResponsesChatModel:
        return self.model_copy(update={"bound_tools": list(tools or [])})

    # subclass hooks -------------------------------------------------------
    async def build_request(
        self, messages: list[BaseMessage], session: dict[str, Any], session_id: str | None
    ) -> tuple[str, dict[str, str], dict[str, Any]]:
        raise NotImplementedError

    def _session_id(self, kwargs: dict[str, Any]) -> str | None:
        """The harness session: the LangGraph thread of the running graph, else an explicit hint."""
        try:
            thread = dict(get_config().get("configurable") or {}).get("thread_id")
            if thread:
                return str(thread)
        except Exception:  # noqa: BLE001 - outside a graph run
            pass
        config = kwargs.get("config") or {}
        configurable = config.get("configurable") if isinstance(config, dict) else {}
        return (configurable or {}).get("thread_id") or self.session_id_hint

    # generation -----------------------------------------------------------
    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        return asyncio.run(self._agenerate(messages, stop=stop, **kwargs))

    def _stream(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> Iterator[ChatGenerationChunk]:
        async def collect() -> list[ChatGenerationChunk]:
            return [c async for c in self._astream(messages, stop=stop, **kwargs)]

        yield from asyncio.run(collect())

    async def _agenerate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: AsyncCallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        final: AIMessageChunk | None = None
        async for chunk in self._astream(messages, stop=stop, run_manager=run_manager, **kwargs):
            final = chunk.message if final is None else final + chunk.message
        message = final if final is not None else AIMessageChunk(content="")
        return ChatResult(
            generations=[
                ChatGeneration(
                    message=AIMessage(
                        content=message.content,
                        tool_calls=message.tool_calls,
                        additional_kwargs=message.additional_kwargs,
                        response_metadata=message.response_metadata,
                        usage_metadata=message.usage_metadata,
                    )
                )
            ]
        )

    async def _astream(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: AsyncCallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[ChatGenerationChunk]:
        provider = self.provider_ref
        manager = provider.token_manager(self.account_key)
        session = await manager.session()
        session_id = self._session_id(kwargs)
        for attempt in (1, 2):
            url, headers, body = await self.build_request(messages, session, session_id)
            translator = ResponsesTranslator(self.label)
            try:
                async with provider.http.stream(
                    "POST", url, headers=headers, json=body, timeout=httpx.Timeout(60.0, read=self.stream_idle_timeout)
                ) as res:
                    if res.status_code == 401 and attempt == 1:
                        session = await manager.session(force=True)
                        continue
                    if res.status_code >= 400:
                        raise http_error(self.label, res.status_code, await read_error(res))
                    async for event in iter_sse(res, self.label, self.stream_idle_timeout):
                        for chunk in translator.feed(event.event, event.data):
                            gen = ChatGenerationChunk(message=chunk)
                            if run_manager is not None and isinstance(chunk.content, str) and chunk.content:
                                await run_manager.on_llm_new_token(chunk.content, chunk=gen)
                            yield gen
                if not translator.completed:
                    raise LlmError("STREAM_CLOSED", f"{self.label} stream ended before completion")
                return
            except httpx.HTTPError as exc:
                raise LlmError("TRANSPORT", f"{self.label}: {exc}") from exc
