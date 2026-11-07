"""Message content helpers: text, images and reasoning of LangChain messages; serialization for the API."""

from __future__ import annotations

import json
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, ToolMessage


def _text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and block.get("type") == "text":
                parts.append(str(block.get("text", "")))
        return "".join(parts)
    return "" if content is None else str(content)


def _images(content: Any) -> list[str]:
    """Image URLs (data URLs included) of ``image_url`` / ``image`` content blocks."""
    if not isinstance(content, list):
        return []
    out: list[str] = []
    for block in content:
        if not isinstance(block, dict):
            continue
        kind = block.get("type")
        if kind == "image_url":
            url = block.get("image_url")
            url = url.get("url") if isinstance(url, dict) else url
            if isinstance(url, str) and url:
                out.append(url)
        elif kind == "image":
            data = block.get("base64") or block.get("data")
            mime = block.get("mime_type") or block.get("mimeType") or "image/png"
            if isinstance(data, str) and data:
                out.append(f"data:{mime};base64,{data}")
            elif isinstance(block.get("url"), str):
                out.append(block["url"])
    return out


def user_content(text: str, images: list[str] | None = None) -> Any:
    """Content of a user message: plain text, or text and ``image_url`` blocks."""
    if not images:
        return text
    blocks: list[dict[str, Any]] = [{"type": "text", "text": text}] if text else []
    blocks += [{"type": "image_url", "image_url": {"url": url}} for url in images]
    return blocks


def _reasoning(message: BaseMessage) -> str:
    """Reasoning text of an AI message: ``reasoning_content`` (DeepSeek) or reasoning/thinking blocks."""
    extra = getattr(message, "additional_kwargs", None) or {}
    text = extra.get("reasoning_content")
    if isinstance(text, str) and text:
        return text
    if isinstance(message.content, list):
        parts = []
        for block in message.content:
            if isinstance(block, dict) and block.get("type") in ("reasoning", "thinking"):
                value = block.get("reasoning") or block.get("thinking") or block.get("text")
                if isinstance(value, str):
                    parts.append(value)
        return "".join(parts)
    return ""


def _iter_messages(update: Any) -> list[BaseMessage]:
    if not isinstance(update, dict):
        return []
    messages = update.get("messages")
    if isinstance(messages, BaseMessage):
        return [messages]
    if isinstance(messages, (list, tuple)):
        return [m for m in messages if isinstance(m, BaseMessage)]
    value = getattr(messages, "value", None)  # Overwrite(...)
    if isinstance(value, (list, tuple)):
        return [m for m in value if isinstance(m, BaseMessage)]
    return []


def serialize_message(message: BaseMessage) -> dict[str, Any]:
    data: dict[str, Any] = {"id": message.id, "role": message.type, "content": _text(message.content)}
    if images := _images(message.content):
        data["images"] = images
    if isinstance(message, AIMessage) and (reasoning := _reasoning(message)):
        data["reasoning"] = reasoning
    marker = (getattr(message, "additional_kwargs", None) or {}).get("pyharness")
    if isinstance(marker, dict):
        data["harness"] = marker  # message written by the harness
    if isinstance(message, AIMessage) and message.tool_calls:
        data["tool_calls"] = [
            {"id": tc.get("id"), "name": tc["name"], "args": tc.get("args", {})} for tc in message.tool_calls
        ]
    if isinstance(message, ToolMessage):
        data["tool_call_id"] = message.tool_call_id
        data["name"] = message.name
        data["status"] = message.status
    return data


def _checkpoint(message: BaseMessage) -> dict[str, Any] | None:
    """Marker of a compaction checkpoint message (``{"kind": "compact-checkpoint", ...}``), else ``None``."""
    marker = (getattr(message, "additional_kwargs", None) or {}).get("pyharness")
    return marker if isinstance(marker, dict) and marker.get("kind") == "compact-checkpoint" else None


def _summary(content: Any) -> str:
    text = _text(content)
    start, end = text.find("<compacted-summary>"), text.rfind("</compacted-summary>")
    return text[start + len("<compacted-summary>") : end].strip() if 0 <= start < end else text


def _jsonable(value: Any) -> Any:
    try:
        json.dumps(value)
        return value
    except TypeError:
        return json.loads(json.dumps(value, default=str))
