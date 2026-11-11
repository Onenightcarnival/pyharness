"""Anthropic Messages: request parsing, the content-block event stream and the complete message object.

| name                       | contract                                                                    |
|----------------------------|-----------------------------------------------------------------------------|
| ``parse_request()``        | body → ``ParsedRequest``; ``thinking`` blocks of earlier turns are dropped  |
| ``AnthropicStreamEncoder`` | ``message_start`` … ``message_stop``; a ``tool_use`` block opens on its first delta |
| ``message()``              | the ``message`` object of a finished generation                             |
| ``error_body()``           | ``{"type": "error", "error": {type, message}}``                             |
"""

from __future__ import annotations

from typing import Any

from .chunks import Chunk, finish_failure, full_usage
from .drafts import (
    Block,
    Draft,
    ParsedRequest,
    arguments_object,
    arguments_text,
    invalid,
    is_record,
    join_system,
    optional_boolean,
    optional_integer,
    optional_number,
    optional_string,
    parameter_schema,
    request_id,
    sse,
    stop_sequences,
    text_block,
    text_of,
    tool_name,
    unsupported,
)

ERROR_TYPES = {
    "invalid_request_error": "invalid_request_error",
    "unsupported_parameter": "invalid_request_error",
    "authentication_error": "authentication_error",
    "permission_error": "permission_error",
    "not_found_error": "not_found_error",
    "model_not_found": "not_found_error",
}


def _image(source: Any, where: str) -> Block:
    if not is_record(source):
        raise invalid(f'"{where}.source" must be an object', where)
    if source.get("type") == "base64":
        if not isinstance(source.get("media_type"), str) or not isinstance(source.get("data"), str):
            raise invalid(f'"{where}.source" must carry media_type and data', where)
        return {
            "type": "pending-image",
            "source": {"kind": "base64", "media_type": source["media_type"], "data": source["data"]},
        }
    if source.get("type") == "url":
        if not isinstance(source.get("url"), str) or not source["url"]:
            raise invalid(f'"{where}.source.url" must be a string', where)
        return {"type": "pending-image", "source": {"kind": "url", "url": source["url"]}}
    raise unsupported(f"{where}.source.type={source.get('type')}")


def _plain(content: Any, where: str, allow_images: bool) -> list[Block]:
    """Text and image blocks of one content value."""
    if content is None:
        return []
    if isinstance(content, str):
        return [text_block(content)] if content else []
    if not isinstance(content, list):
        raise invalid(f'"{where}" must be a string or a list of blocks', where)
    blocks: list[Block] = []
    for index, block in enumerate(content):
        at = f"{where}[{index}]"
        if not is_record(block):
            raise invalid(f'"{at}" must be an object', at)
        if block.get("type") == "text":
            if not isinstance(block.get("text"), str):
                raise invalid(f'"{at}.text" must be a string', at)
            blocks.append(text_block(block["text"]))
        elif block.get("type") == "image" and allow_images:
            blocks.append(_image(block.get("source"), at))
        else:
            raise unsupported(f"{at}.type={block.get('type')}")
    return blocks


def _tools(value: Any) -> list[dict[str, Any]] | None:
    if value is None:
        return None
    if not isinstance(value, list):
        raise invalid('"tools" must be a list', "tools")
    tools = []
    for index, tool in enumerate(value):
        where = f"tools[{index}]"
        if not is_record(tool):
            raise invalid(f'"{where}" must be an object', where)
        if tool.get("type") not in (None, "custom"):
            raise unsupported(f"{where}.type={tool.get('type')}")
        description = tool.get("description")
        tools.append(
            {
                "name": tool_name(tool.get("name"), f"{where}.name"),
                "description": description if isinstance(description, str) else "",
                "parameters": parameter_schema(tool.get("input_schema"), f"{where}.input_schema"),
            }
        )
    return tools


def _message(message: dict[str, Any], where: str) -> list[Draft]:
    """Draft messages of one request message: tool results first, then the message's own content."""
    role = message["role"]
    if isinstance(message.get("content"), str):
        return [{"role": role, "content": [text_block(message["content"])] if message["content"] else []}]
    if not isinstance(message.get("content"), list):
        raise invalid(f'"{where}.content" must be a string or a list of blocks', where)
    content: list[Block] = []
    results: list[Draft] = []
    for index, block in enumerate(message["content"]):
        at = f"{where}.content[{index}]"
        if not is_record(block):
            raise invalid(f'"{at}" must be an object', at)
        kind = block.get("type")
        if kind == "text":
            if not isinstance(block.get("text"), str):
                raise invalid(f'"{at}.text" must be a string', at)
            content.append(text_block(block["text"]))
        elif kind == "image":
            if role != "user":
                raise unsupported(f"{at}.type=image in an assistant message")
            content.append(_image(block.get("source"), at))
        elif kind == "tool_use":
            if role != "assistant":
                raise invalid(f'"{at}" tool_use belongs to assistant messages', at)
            if not isinstance(block.get("id"), str) or not block["id"]:
                raise invalid(f'"{at}.id" must be a string', at)
            content.append(
                {
                    "type": "tool-call",
                    "id": block["id"],
                    "name": tool_name(block.get("name"), f"{at}.name"),
                    "arguments": arguments_text(block.get("input")),
                }
            )
        elif kind == "tool_result":
            if role != "user":
                raise invalid(f'"{at}" tool_result belongs to user messages', at)
            if not isinstance(block.get("tool_use_id"), str) or not block["tool_use_id"]:
                raise invalid(f'"{at}.tool_use_id" must be a string', at)
            results.append(
                {
                    "role": "tool",
                    "call_id": block["tool_use_id"],
                    "content": _plain(block.get("content"), f"{at}.content", True),
                    "is_error": block.get("is_error") is True,
                }
            )
        elif kind not in ("thinking", "redacted_thinking"):
            raise unsupported(f"{at}.type={kind}")
    return [*results, {"role": role, "content": content}] if content or not results else results


def parse_request(body: Any) -> ParsedRequest:
    if not is_record(body):
        raise invalid("request body must be a JSON object")
    if not isinstance(body.get("messages"), list) or not body["messages"]:
        raise invalid('"messages" must be a non-empty list', "messages")
    system: list[str] = []
    if isinstance(body.get("system"), str):
        system.append(body["system"])
    elif body.get("system") is not None:
        system.append(text_of(_plain(body["system"], "system", False)))
    messages: list[Draft] = []
    for index, message in enumerate(body["messages"]):
        where = f"messages[{index}]"
        if not is_record(message):
            raise invalid(f'"{where}" must be an object', where)
        if message.get("role") not in ("user", "assistant"):
            raise invalid(f'"{where}.role" must be user or assistant', where)
        messages.extend(_message(message, where))
    declared = _tools(body.get("tools"))
    tool_choice = body["tool_choice"].get("type") if is_record(body.get("tool_choice")) else None
    return ParsedRequest(
        model=optional_string(body.get("model"), "model"),
        stream=optional_boolean(body.get("stream"), "stream") or False,
        include_usage=True,
        system=join_system(system),
        messages=messages,
        tools=None if tool_choice == "none" else declared,
        temperature=optional_number(body.get("temperature"), "temperature", 0, 1),
        max_tokens=optional_integer(body.get("max_tokens"), "max_tokens"),
        stop=stop_sequences(body.get("stop_sequences"), "stop_sequences"),
        reasoning_effort=None,
    )


def stop_reason(reason: dict[str, Any]) -> str:
    return {"tool-calls": "tool_use", "max-tokens": "max_tokens"}.get(reason["kind"], "end_turn")


def _usage(usage: dict[str, int] | None) -> dict[str, Any]:
    full = full_usage(usage)
    return {
        "input_tokens": full["input_tokens"],
        "output_tokens": full["output_tokens"],
        "cache_read_input_tokens": full["cache_read_tokens"],
        "cache_creation_input_tokens": full["cache_write_tokens"],
    }


def error_body(code: str, message: str) -> dict[str, Any]:
    return {"type": "error", "error": {"type": ERROR_TYPES.get(code, "api_error"), "message": message}}


def content_of(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    content: list[dict[str, Any]] = []
    for block in blocks:
        if block["type"] == "text":
            content.append({"type": "text", "text": block["text"]})
        elif block["type"] == "reasoning":
            content.append({"type": "thinking", "thinking": block["text"], "signature": ""})
        elif block["type"] == "tool-call":
            content.append(
                {
                    "type": "tool_use",
                    "id": block["id"],
                    "name": block["name"],
                    "input": arguments_object(block["arguments"]),
                }
            )
    return content


def message(
    model: str, blocks: list[dict[str, Any]], usage: dict[str, int] | None, reason: dict[str, Any]
) -> dict[str, Any]:
    return {
        "id": request_id("msg_"),
        "type": "message",
        "role": "assistant",
        "model": model,
        "content": content_of(blocks),
        "stop_reason": stop_reason(reason),
        "stop_sequence": None,
        "usage": _usage(usage),
    }


class AnthropicStreamEncoder:
    """Anthropic event stream; content blocks are numbered in the order they open."""

    def __init__(self, model: str) -> None:
        self.model = model
        self.id = request_id("msg_")
        self._blocks: dict[int, dict[str, Any]] = {}  # block index → {index, started}
        self._next = 0
        self._usage: dict[str, int] | None = None

    def _event(self, kind: str, **payload: Any) -> str:
        return sse({"type": kind, **payload}, kind)

    def _block(self, index: int) -> dict[str, Any]:
        if index not in self._blocks:
            self._blocks[index] = {"index": self._next, "started": False}
            self._next += 1
        return self._blocks[index]

    def _begin(self, block: dict[str, Any], content_block: dict[str, Any]) -> str:
        if block["started"]:
            return ""
        block["started"] = True
        return self._event("content_block_start", index=block["index"], content_block=content_block)

    def _delta(self, block: dict[str, Any], delta: dict[str, Any]) -> str:
        return self._event("content_block_delta", index=block["index"], delta=delta)

    def _stop(self, index: int) -> str:
        block = self._blocks.pop(index, None)
        return self._event("content_block_stop", index=block["index"]) if block and block["started"] else ""

    def start(self) -> str:
        return self._event(
            "message_start",
            message={
                "id": self.id,
                "type": "message",
                "role": "assistant",
                "model": self.model,
                "content": [],
                "stop_reason": None,
                "stop_sequence": None,
                "usage": {"input_tokens": 0, "output_tokens": 0},
            },
        )

    def push(self, chunk: Chunk) -> str:
        kind = chunk["type"]
        if kind == "block-start":
            block = self._block(chunk["index"])
            if chunk["block_type"] == "text":
                return self._begin(block, {"type": "text", "text": ""})
            if chunk["block_type"] == "reasoning":
                return self._begin(block, {"type": "thinking", "thinking": ""})
            return ""
        if kind == "text-delta":
            block = self._block(chunk["index"])
            frames = self._begin(block, {"type": "text", "text": ""})
            return frames + (self._delta(block, {"type": "text_delta", "text": chunk["text"]}) if chunk["text"] else "")
        if kind == "reasoning-delta":
            block = self._block(chunk["index"])
            frames = self._begin(block, {"type": "thinking", "thinking": ""})
            delta = {"type": "thinking_delta", "thinking": chunk["text"]}
            return frames + (self._delta(block, delta) if chunk["text"] else "")
        if kind == "tool-call-delta":
            block = self._block(chunk["index"])
            opened = {"type": "tool_use", "id": chunk["id"], "name": chunk.get("name", ""), "input": {}}
            delta = {"type": "input_json_delta", "partial_json": chunk["arguments_delta"]}
            return self._begin(block, opened) + (self._delta(block, delta) if chunk["arguments_delta"] else "")
        if kind == "block-end":
            return self._stop(chunk["index"])
        if kind == "usage":
            self._usage = chunk["usage"]
            return ""
        if kind == "finish":
            failure = finish_failure(chunk["reason"])
            if failure is not None:
                return self.fail(failure)
            frames = "".join(self._stop(index) for index in list(self._blocks))
            delta = {"stop_reason": stop_reason(chunk["reason"]), "stop_sequence": None}
            return (
                frames
                + self._event("message_delta", delta=delta, usage=_usage(self._usage))
                + self._event("message_stop")
            )
        return ""

    def end(self) -> str:
        return ""

    def fail(self, error: dict[str, Any]) -> str:
        return self._event("error", error={"type": "api_error", "message": f"{error['code']}: {error['message']}"})
