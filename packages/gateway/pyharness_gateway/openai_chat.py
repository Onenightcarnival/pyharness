from __future__ import annotations

import time
from typing import Any

from .chunks import Chunk, finish_failure, full_usage
from .drafts import (
    Block,
    Draft,
    ParsedRequest,
    arguments_text,
    image_from_url,
    invalid,
    is_record,
    join_system,
    optional_boolean,
    optional_integer,
    optional_number,
    optional_string,
    parameter_schema,
    push_assistant,
    request_id,
    sse,
    stop_sequences,
    text_block,
    text_of,
    tool_name,
    unsupported,
)

CLIENT_ERRORS = ("invalid_request_error", "unsupported_parameter")


def _blocks(content: Any, param: str, allow_images: bool) -> list[Block]:
    if content is None:
        return []
    if isinstance(content, str):
        return [text_block(content)] if content else []
    if not isinstance(content, list):
        raise invalid(f'"{param}" must be a string or a list of content parts', param)
    blocks: list[Block] = []
    for index, part in enumerate(content):
        where = f"{param}[{index}]"
        if not is_record(part):
            raise invalid(f'"{where}" must be an object', where)
        if part.get("type") == "text":
            if not isinstance(part.get("text"), str):
                raise invalid(f'"{where}.text" must be a string', where)
            blocks.append(text_block(part["text"]))
        elif part.get("type") == "image_url" and allow_images:
            image = part.get("image_url")
            url = image if isinstance(image, str) else image.get("url") if is_record(image) else None
            if not isinstance(url, str) or not url:
                raise invalid(f'"{where}.image_url" must carry a URL', where)
            blocks.append(image_from_url(url))
        else:
            raise unsupported(f"{where}.type={part.get('type')}")
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
        if tool.get("type") != "function":
            raise unsupported(f"{where}.type={tool.get('type')}")
        function = tool.get("function")
        if not is_record(function):
            raise invalid(f'"{where}.function" must be an object', where)
        description = function.get("description")
        tools.append(
            {
                "name": tool_name(function.get("name"), f"{where}.function.name"),
                "description": description if isinstance(description, str) else "",
                "parameters": parameter_schema(function.get("parameters"), f"{where}.function.parameters"),
            }
        )
    return tools


def _assistant(message: dict[str, Any], where: str) -> list[Block]:
    content = _blocks(message.get("content"), f"{where}.content", False)
    calls = message.get("tool_calls")
    if calls is None:
        return content
    if not isinstance(calls, list):
        raise invalid(f'"{where}.tool_calls" must be a list', where)
    for index, call in enumerate(calls):
        at = f"{where}.tool_calls[{index}]"
        if not is_record(call) or not is_record(call.get("function")):
            raise invalid(f'"{at}" must carry a function', at)
        if not isinstance(call.get("id"), str) or not call["id"]:
            raise invalid(f'"{at}.id" must be a string', at)
        function = call["function"]
        content.append(
            {
                "type": "tool-call",
                "id": call["id"],
                "name": tool_name(function.get("name"), f"{at}.function.name"),
                "arguments": arguments_text(function.get("arguments")),
            }
        )
    return content


def parse_request(body: Any) -> ParsedRequest:
    if not is_record(body):
        raise invalid("request body must be a JSON object")
    if optional_integer(body.get("n"), "n") not in (None, 1):
        raise unsupported("n")
    if body.get("logprobs") is True or body.get("top_logprobs") is not None:
        raise unsupported("logprobs")
    response_format = body.get("response_format")
    if is_record(response_format) and response_format.get("type") not in (None, "text"):
        raise unsupported(f"response_format.type={response_format.get('type')}")
    if not isinstance(body.get("messages"), list) or not body["messages"]:
        raise invalid('"messages" must be a non-empty list', "messages")
    system: list[str] = []
    messages: list[Draft] = []
    for index, message in enumerate(body["messages"]):
        where = f"messages[{index}]"
        if not is_record(message):
            raise invalid(f'"{where}" must be an object', where)
        role = message.get("role")
        if role in ("system", "developer"):
            system.append(text_of(_blocks(message.get("content"), f"{where}.content", False)))
        elif role == "user":
            messages.append({"role": "user", "content": _blocks(message.get("content"), f"{where}.content", True)})
        elif role == "assistant":
            push_assistant(messages, _assistant(message, where))
        elif role == "tool":
            if not isinstance(message.get("tool_call_id"), str) or not message["tool_call_id"]:
                raise invalid(f'"{where}.tool_call_id" must be a string', where)
            messages.append(
                {
                    "role": "tool",
                    "call_id": message["tool_call_id"],
                    "content": _blocks(message.get("content"), f"{where}.content", False),
                    "is_error": False,
                }
            )
        else:
            raise unsupported(f"{where}.role={role}")
    declared = _tools(body.get("tools"))
    stream_options = body.get("stream_options") if is_record(body.get("stream_options")) else {}
    max_tokens = optional_integer(body.get("max_completion_tokens"), "max_completion_tokens")
    return ParsedRequest(
        model=optional_string(body.get("model"), "model"),
        stream=optional_boolean(body.get("stream"), "stream") or False,
        include_usage=optional_boolean(stream_options.get("include_usage"), "stream_options.include_usage") or False,
        system=join_system(system),
        messages=messages,
        tools=None if body.get("tool_choice") == "none" else declared,
        temperature=optional_number(body.get("temperature"), "temperature", 0, 2),
        max_tokens=max_tokens if max_tokens is not None else optional_integer(body.get("max_tokens"), "max_tokens"),
        stop=stop_sequences(body.get("stop"), "stop"),
        reasoning_effort=optional_string(body.get("reasoning_effort"), "reasoning_effort"),
    )


def finish_reason(reason: dict[str, Any]) -> str:
    return {"tool-calls": "tool_calls", "max-tokens": "length"}.get(reason["kind"], "stop")


def _usage(usage: dict[str, int] | None) -> dict[str, Any]:
    full = full_usage(usage)
    return {
        "prompt_tokens": full["input_tokens"],
        "completion_tokens": full["output_tokens"],
        "total_tokens": full["total_tokens"],
        "prompt_tokens_details": {"cached_tokens": full["cache_read_tokens"]},
        "completion_tokens_details": {"reasoning_tokens": full["reasoning_tokens"]},
    }


def error_body(code: str, message: str, param: str | None = None) -> dict[str, Any]:
    kind = "invalid_request_error" if code in CLIENT_ERRORS else "server_error"
    return {"error": {"message": message, "type": kind, "code": code, "param": param}}


def completion(
    model: str, blocks: list[dict[str, Any]], usage: dict[str, int] | None, reason: dict[str, Any]
) -> dict[str, Any]:
    content = "".join(b["text"] for b in blocks if b["type"] == "text")
    reasoning = "".join(b["text"] for b in blocks if b["type"] == "reasoning")
    calls = [
        {"id": b["id"], "type": "function", "function": {"name": b["name"], "arguments": b["arguments"]}}
        for b in blocks
        if b["type"] == "tool-call"
    ]
    message: dict[str, Any] = {"role": "assistant", "content": None if not content and calls else content}
    if reasoning:
        message["reasoning_content"] = reasoning
    if calls:
        message["tool_calls"] = calls
    return {
        "id": request_id("chatcmpl-"),
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model,
        "choices": [{"index": 0, "message": message, "logprobs": None, "finish_reason": finish_reason(reason)}],
        "usage": _usage(usage),
    }


class ChatStreamEncoder:
    """``chat.completion.chunk`` frames; the first delta carries the assistant role."""

    def __init__(self, model: str, include_usage: bool) -> None:
        self.model = model
        self.include_usage = include_usage
        self.id = request_id("chatcmpl-")
        self.created = int(time.time())
        self._ordinals: dict[int, int] = {}  # block index → position in `tool_calls`
        self._announced: set[int] = set()
        self._role_sent = False
        self._usage: dict[str, int] | None = None

    def _frame(self, choices: list[dict[str, Any]], **extra: Any) -> str:
        return sse(
            {
                "id": self.id,
                "object": "chat.completion.chunk",
                "created": self.created,
                "model": self.model,
                "choices": choices,
                **extra,
            }
        )

    def _chunk(self, delta: dict[str, Any], reason: str | None = None) -> str:
        payload = delta if self._role_sent else {"role": "assistant", **delta}
        self._role_sent = True
        return self._frame([{"index": 0, "delta": payload, "logprobs": None, "finish_reason": reason}])

    def start(self) -> str:
        return ""

    def push(self, chunk: Chunk) -> str:
        kind = chunk["type"]
        if kind == "text-delta":
            return self._chunk({"content": chunk["text"]}) if chunk["text"] else ""
        if kind == "reasoning-delta":
            return self._chunk({"reasoning_content": chunk["text"]}) if chunk["text"] else ""
        if kind == "tool-call-delta":
            index = chunk["index"]
            ordinal = self._ordinals.setdefault(index, len(self._ordinals))
            first = index not in self._announced
            self._announced.add(index)
            function: dict[str, Any] = {"arguments": chunk["arguments_delta"]}
            if first or "name" in chunk:
                function["name"] = chunk.get("name", "")
            call: dict[str, Any] = {"index": ordinal, "function": function}
            if first:
                call |= {"id": chunk["id"], "type": "function"}
            return self._chunk({"tool_calls": [call]})
        if kind == "usage":
            self._usage = chunk["usage"]
            return ""
        if kind == "finish":
            failure = finish_failure(chunk["reason"])
            if failure is not None:
                return self.fail(failure)
            frames = self._chunk({}, finish_reason(chunk["reason"]))
            if self.include_usage:
                frames += self._frame([], usage=_usage(self._usage))
            return frames
        return ""

    def end(self) -> str:
        return "data: [DONE]\n\n"

    def fail(self, error: dict[str, Any]) -> str:
        return sse({"error": {"message": error["message"], "type": "server_error", "code": error["code"]}})
