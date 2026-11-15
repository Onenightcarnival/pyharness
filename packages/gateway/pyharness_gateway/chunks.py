"""
Stream vocabulary of the gateway: a LangChain message stream becomes block chunks the protocol encoders consume.

| chunk             | fields                                                              |
|-------------------|---------------------------------------------------------------------|
| ``block-start``   | ``index``, ``block_type`` (``text``, ``reasoning``, ``tool-call``)  |
| ``text-delta``    | ``index``, ``text``                                                 |
| ``reasoning-delta`` | ``index``, ``text``                                               |
| ``tool-call-delta`` | ``index``, ``id``, ``arguments_delta``; ``name`` on the first delta |
| ``block-end``     | ``index``                                                           |
| ``usage``         | ``usage``: token counters                                           |
| ``finish``        | ``reason``: ``{kind}`` of ``stop``, ``tool-calls``, ``max-tokens``; ``error`` adds ``failure`` |

| name               | contract                                                                        |
|--------------------|---------------------------------------------------------------------------------|
| ``normalize()``    | chunks of one LangChain ``astream``; one text or reasoning block is open at a time |
|                    | and tool calls stay open until the finish                                       |
| ``BlockAssembler`` | collects chunks into finished blocks, the usage and the finish reason           |
| ``full_usage()``   | usage with every counter present                                                |
| ``finish_failure()`` | ``{code, message, status}`` of an ``error`` finish; ``None`` for a normal one |

Reasoning text is read from ``additional_kwargs["reasoning_content"]`` and from ``reasoning`` / ``thinking`` content
blocks. A message without ``tool_call_chunks`` (a model that does not stream) contributes its ``tool_calls`` whole.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from langchain_core.messages import BaseMessage
from langchain_core.messages.ai import add_usage

from .drafts import compact_json

Chunk = dict[str, Any]
COUNTERS = (
    "input_tokens",
    "output_tokens",
    "total_tokens",
    "cache_read_tokens",
    "cache_write_tokens",
    "reasoning_tokens",
)
LENGTH_REASONS = ("length", "max_tokens")
TOOL_REASONS = ("tool_calls", "tool_use")


def full_usage(usage: dict[str, int] | None) -> dict[str, int]:
    usage = usage or {}
    out = {name: int(usage.get(name) or 0) for name in COUNTERS}
    out["total_tokens"] = int(usage.get("total_tokens") or out["input_tokens"] + out["output_tokens"])
    return out


def finish_failure(reason: dict[str, Any]) -> dict[str, Any] | None:
    if reason.get("kind") not in ("error", "aborted"):
        return None
    failure = reason.get("failure") or {}
    status = failure.get("status")
    return {
        "code": failure.get("code") or "upstream_error",
        "message": failure.get("message") or "",
        "status": status if isinstance(status, int) and 400 <= status <= 599 else 502,
    }


def is_content_delta(chunk: Chunk) -> bool:
    return chunk["type"] in ("text-delta", "reasoning-delta", "tool-call-delta")


def _usage(metadata: dict[str, Any]) -> dict[str, int]:
    inputs = metadata.get("input_token_details") or {}
    outputs = metadata.get("output_token_details") or {}
    return {
        "input_tokens": metadata.get("input_tokens") or 0,
        "output_tokens": metadata.get("output_tokens") or 0,
        "total_tokens": metadata.get("total_tokens") or 0,
        "cache_read_tokens": inputs.get("cache_read") or 0,
        "cache_write_tokens": inputs.get("cache_creation") or 0,
        "reasoning_tokens": outputs.get("reasoning") or 0,
    }


def _text(content: Any) -> str:
    if isinstance(content, str):
        return content
    parts = []
    for block in content if isinstance(content, list) else []:
        if isinstance(block, str):
            parts.append(block)
        elif isinstance(block, dict) and block.get("type") == "text":
            parts.append(str(block.get("text") or ""))
    return "".join(parts)


def _reasoning(message: BaseMessage) -> str:
    text = (getattr(message, "additional_kwargs", None) or {}).get("reasoning_content")
    if isinstance(text, str) and text:
        return text
    parts = []
    for block in message.content if isinstance(message.content, list) else []:
        if not isinstance(block, dict) or block.get("type") not in ("reasoning", "thinking"):
            continue
        value = block.get("reasoning") or block.get("thinking") or block.get("text")
        if isinstance(value, str):
            parts.append(value)
        parts.extend(str(s.get("text") or "") for s in block.get("summary") or [] if isinstance(s, dict))
    return "".join(parts)


def _tool_chunks(message: BaseMessage) -> list[dict[str, Any]]:
    chunks = getattr(message, "tool_call_chunks", None)
    if chunks:
        return list(chunks)
    return [
        {"index": None, "id": call.get("id"), "name": call.get("name"), "args": compact_json(call.get("args") or {})}
        for call in getattr(message, "tool_calls", None) or []
    ]


class _Blocks:
    """Block bookkeeping of one stream."""

    def __init__(self) -> None:
        self.next_index = 0
        self.open: tuple[str, int] | None = None  # the open text or reasoning block: (block type, index)
        self.tools: dict[Any, dict[str, Any]] = {}  # provider tool key → {index, id}
        self.last_tool: Any = None

    def _close(self) -> list[Chunk]:
        if self.open is None:
            return []
        index, self.open = self.open[1], None
        return [{"type": "block-end", "index": index}]

    def _delta(self, block_type: str, text: str) -> list[Chunk]:
        out: list[Chunk] = []
        if self.open is None or self.open[0] != block_type:
            out += self._close()
            self.open = (block_type, self.next_index)
            self.next_index += 1
            out.append({"type": "block-start", "index": self.open[1], "block_type": block_type})
        out.append({"type": f"{block_type}-delta", "index": self.open[1], "text": text})
        return out

    def _tool(self, chunk: dict[str, Any]) -> list[Chunk]:
        key = chunk.get("index")
        if key is None:
            # A delta without index and id continues the last call; an id starts or continues its own call.
            key = chunk.get("id") or self.last_tool
        out: list[Chunk] = []
        if key is None or key not in self.tools:
            key = key if key is not None else f"call-{len(self.tools)}"
            out += self._close()
            self.tools[key] = {"index": self.next_index, "id": chunk.get("id") or f"call_{self.next_index}"}
            self.next_index += 1
            out.append({"type": "block-start", "index": self.tools[key]["index"], "block_type": "tool-call"})
        self.last_tool = key
        tool = self.tools[key]
        delta: Chunk = {
            "type": "tool-call-delta",
            "index": tool["index"],
            "id": tool["id"],
            "arguments_delta": chunk.get("args") or "",
        }
        if chunk.get("name"):
            delta["name"] = chunk["name"]
        out.append(delta)
        return out

    def feed(self, message: BaseMessage) -> list[Chunk]:
        out: list[Chunk] = []
        reasoning, text = _reasoning(message), _text(message.content)
        if reasoning:
            out += self._delta("reasoning", reasoning)
        if text:
            out += self._delta("text", text)
        for chunk in _tool_chunks(message):
            out += self._tool(chunk)
        return out

    def finish(self) -> list[Chunk]:
        ends = [{"type": "block-end", "index": tool["index"]} for tool in self.tools.values()]
        return self._close() + ends


async def normalize(stream: AsyncIterator[BaseMessage]) -> AsyncIterator[Chunk]:
    blocks = _Blocks()
    usage: Any = None
    reason = ""
    async for message in stream:
        for chunk in blocks.feed(message):
            yield chunk
        usage = add_usage(usage, getattr(message, "usage_metadata", None)) if usage or message.usage_metadata else usage
        metadata = getattr(message, "response_metadata", None) or {}
        reason = metadata.get("finish_reason") or metadata.get("stop_reason") or reason
    for chunk in blocks.finish():
        yield chunk
    if usage:
        yield {"type": "usage", "usage": _usage(usage)}
    kind = (
        "tool-calls" if blocks.tools or reason in TOOL_REASONS else "max-tokens" if reason in LENGTH_REASONS else "stop"
    )
    yield {"type": "finish", "reason": {"kind": kind}}


class BlockAssembler:
    """Finished blocks of a chunk stream: text, reasoning (``text``) and tool-call (``id``, ``name``, ``arguments``)."""

    def __init__(self) -> None:
        self._blocks: dict[int, dict[str, Any]] = {}
        self.usage: dict[str, int] | None = None
        self.finish: dict[str, Any] | None = None

    def push(self, chunk: Chunk) -> None:
        kind = chunk["type"]
        if kind == "usage":
            self.usage = chunk["usage"]
        elif kind == "finish":
            self.finish = chunk["reason"]
        elif kind in ("text-delta", "reasoning-delta"):
            block = self._blocks.setdefault(chunk["index"], {"type": kind.removesuffix("-delta"), "text": ""})
            block["text"] += chunk["text"]
        elif kind == "tool-call-delta":
            block = self._blocks.setdefault(
                chunk["index"], {"type": "tool-call", "id": chunk["id"], "name": "", "arguments": ""}
            )
            block["name"] = block["name"] or chunk.get("name") or ""
            block["arguments"] += chunk["arguments_delta"]

    def blocks(self) -> list[dict[str, Any]]:
        return [self._blocks[index] for index in sorted(self._blocks)]
