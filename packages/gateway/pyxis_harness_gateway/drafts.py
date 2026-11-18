from __future__ import annotations

import json
import math
import re
import secrets
import string
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage

from .models import Target

DATA_URL = re.compile(r"^data:([^;,]+)(;[^,]*)?,(.*)$", re.DOTALL)
ID_ALPHABET = string.ascii_lowercase + string.digits
EMPTY_SCHEMA: dict[str, Any] = {"type": "object", "properties": {}}

Block = dict[str, Any]
Draft = dict[str, Any]
ImageLoader = Callable[[Block], Awaitable[str]]


class GatewayError(Exception):
    """Request-level failure reported under ``status`` with ``code``; ``param`` names the offending field."""

    def __init__(self, status: int, code: str, message: str, param: str | None = None) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.param = param


def invalid(message: str, param: str | None = None) -> GatewayError:
    return GatewayError(400, "invalid_request_error", message, param)


def unsupported(param: str) -> GatewayError:
    return GatewayError(400, "unsupported_parameter", f'"{param}" is not supported by this gateway', param)


@dataclass
class ParsedRequest:
    model: str | None
    stream: bool
    # Chat Completions only: ``stream_options.include_usage``; the other protocols always carry usage.
    include_usage: bool
    system: str | None
    messages: list[Draft]
    tools: list[dict[str, Any]] | None
    temperature: float | None
    max_tokens: int | None
    stop: list[str] | None
    reasoning_effort: str | None


@dataclass
class Generation:
    """One model request: the resolved route, LangChain messages, OpenAI-format tools and sampling parameters."""

    target: Target
    messages: list[BaseMessage]
    tools: list[dict[str, Any]] = field(default_factory=list)
    temperature: float | None = None
    max_tokens: int | None = None
    stop: list[str] | None = None
    reasoning_effort: str | None = None


# ---------------------------------------------------------------------- field readers
def is_record(value: Any) -> bool:
    return isinstance(value, dict)


def is_number(value: Any) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool) and math.isfinite(value)


def optional_string(value: Any, param: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise invalid(f'"{param}" must be a string', param)
    return value


def optional_number(value: Any, param: str, low: float | None = None, high: float | None = None) -> float | None:
    if value is None:
        return None
    if not is_number(value):
        raise invalid(f'"{param}" must be a number', param)
    if (low is not None and value < low) or (high is not None and value > high):
        raise invalid(f'"{param}" is out of range', param)
    return value


def optional_integer(value: Any, param: str, low: int = 1) -> int | None:
    number = optional_number(value, param, low)
    if number is None:
        return None
    if number != int(number):
        raise invalid(f'"{param}" must be an integer', param)
    return int(number)


def optional_boolean(value: Any, param: str) -> bool | None:
    if value is None:
        return None
    if not isinstance(value, bool):
        raise invalid(f'"{param}" must be a boolean', param)
    return value


def stop_sequences(value: Any, param: str) -> list[str] | None:
    if value is None:
        return None
    entries = [value] if isinstance(value, str) else value
    if not isinstance(entries, list) or any(not isinstance(entry, str) for entry in entries):
        raise invalid(f'"{param}" must be a string or a list of strings', param)
    return entries or None


def parameter_schema(value: Any, param: str) -> dict[str, Any]:
    """JSON Schema object of tool parameters; an absent schema is an empty object schema."""
    if value is None:
        return dict(EMPTY_SCHEMA)
    if not is_record(value):
        raise invalid(f'"{param}" must be a JSON Schema object', param)
    return value


def tool_name(value: Any, param: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise invalid(f'"{param}" must be a non-empty string', param)
    return value


def compact_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def arguments_text(value: Any) -> str:
    """Tool-call arguments as JSON text: strings pass through, objects are encoded."""
    if isinstance(value, str):
        return value
    return "{}" if value is None else compact_json(value)


def arguments_object(text: str) -> dict[str, Any]:
    """Tool-call argument text as an object; invalid JSON and non-objects become ``{}``."""
    try:
        parsed = json.loads(text or "{}")
    except ValueError:
        return {}
    return parsed if is_record(parsed) else {}


def text_block(text: str) -> Block:
    return {"type": "text", "text": text}


def image_from_url(url: str) -> Block:
    """A pending image of an ``image_url`` value: a base64 ``data:`` URL or a remote URL."""
    match = DATA_URL.match(url)
    if match is None:
        return {"type": "pending-image", "source": {"kind": "url", "url": url}}
    if "base64" not in (match.group(2) or "").split(";"):
        raise invalid("data URLs of images must be base64 encoded")
    return {"type": "pending-image", "source": {"kind": "base64", "media_type": match.group(1), "data": match.group(3)}}


def text_of(blocks: list[Block]) -> str:
    return "".join(block["text"] for block in blocks if block["type"] == "text")


def join_system(parts: list[str]) -> str | None:
    """The request's single system prompt; blank parts are dropped."""
    return "\n\n".join(part for part in parts if part.strip()) or None


def push_assistant(messages: list[Draft], content: list[Block]) -> None:
    """Append assistant content; consecutive assistant items form one message."""
    if messages and messages[-1]["role"] == "assistant":
        messages[-1]["content"].extend(content)
    else:
        messages.append({"role": "assistant", "content": content})


def sse(data: Any, event: str | None = None) -> str:
    """One SSE frame."""
    head = "" if event is None else f"event: {event}\n"
    return f"{head}data: {compact_json(data)}\n\n"


def request_id(prefix: str) -> str:
    return prefix + "".join(secrets.choice(ID_ALPHABET) for _ in range(24))


# ---------------------------------------------------------------------- materialization
async def _content(blocks: list[Block], load_image: ImageLoader) -> Any:
    """LangChain message content: plain text, or content parts when the blocks carry an image."""
    if all(block["type"] == "text" for block in blocks):
        return text_of(blocks)
    parts: list[dict[str, Any]] = []
    for block in blocks:
        if block["type"] == "text":
            parts.append({"type": "text", "text": block["text"]})
        elif block["type"] == "pending-image":
            parts.append({"type": "image_url", "image_url": {"url": await load_image(block)}})
    return parts


async def materialize(parsed: ParsedRequest, target: Target, load_image: ImageLoader) -> Generation:
    """Build the model request: images are loaded, tool calls and tool results keep their call ids."""
    messages: list[BaseMessage] = []
    for draft in parsed.messages:
        blocks = draft["content"]
        if draft["role"] == "user":
            messages.append(HumanMessage(content=await _content(blocks, load_image)))
        elif draft["role"] == "assistant":
            if not blocks:
                continue
            calls = [
                {"type": "tool_call", "id": b["id"], "name": b["name"], "args": arguments_object(b["arguments"])}
                for b in blocks
                if b["type"] == "tool-call"
            ]
            messages.append(AIMessage(content=text_of(blocks), tool_calls=calls))
        else:
            messages.append(
                ToolMessage(
                    content=await _content(blocks, load_image),
                    tool_call_id=draft["call_id"],
                    status="error" if draft["is_error"] else "success",
                )
            )
    if not messages:
        raise invalid("the request carries no messages")
    if parsed.system is not None:
        messages.insert(0, SystemMessage(content=parsed.system))
    return Generation(
        target=target,
        messages=messages,
        tools=[{"type": "function", "function": tool} for tool in parsed.tools or []],
        temperature=parsed.temperature,
        max_tokens=parsed.max_tokens,
        stop=parsed.stop,
        reasoning_effort=parsed.reasoning_effort,
    )
