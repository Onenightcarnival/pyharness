"""
Google Antigravity (Cloud Code Assist ``v1internal``) wire format: contents / parts from LangChain messages, tool
schemas for Gemini and for Claude / gpt-oss models, thinking configuration per model, SSE translation.
"""

from __future__ import annotations

import copy
import json
import re
import time
import uuid
from collections.abc import Iterator
from typing import Any

from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.utils.function_calling import convert_to_openai_tool

from pyharness import package_toml

from .common import LlmError
from .responses import _images_of, _text_of

_CFG = package_toml(__file__)["antigravity_wire"]
DEFAULT_ORIGIN: str = _CFG["DEFAULT_ORIGIN"]
FALLBACK_ORIGIN: str = _CFG["FALLBACK_ORIGIN"]
FALLBACK_STATUSES: set[int] = set(_CFG["FALLBACK_STATUSES"])
UNSUPPORTED_CLIENT = re.compile(_CFG["UNSUPPORTED_CLIENT_PATTERN"], re.IGNORECASE)
UNSUPPORTED_CLIENT_CODE = "UNSUPPORTED_CLIENT"


# ---------------------------------------------------------------------- efforts and thinking
def efforts_for(model: str) -> list[str]:
    m = model.lower()
    if re.match(r"gemini-3\.1-flash(-lite)?-image", m):
        return ["minimal", "high"]
    if m.endswith("-image") or "-image" in m:
        return []
    if m.startswith("claude-"):
        return ["high"]
    if m.startswith("gpt-oss-"):
        return ["medium"]
    if m.startswith("gemini-3.1-pro") or m == "gemini-pro-agent":
        return ["low", "high"]
    tail = re.search(r"-(low|medium|high)$", m)
    if tail:
        return [tail.group(1)]
    if m.startswith(("gemini-2.5", "gemini-3")):
        return ["low", "medium", "high"]
    return []


def thinking_config(model: str, effort: str | None, max_tokens: int | None) -> dict[str, Any] | None:
    m = model.lower()
    if not effort:
        return None
    if effort == "off":
        return {"includeThoughts": False, "thinkingBudget": 0}
    allowed = efforts_for(model)
    if allowed and effort not in allowed:
        raise LlmError(
            "UNSUPPORTED_REASONING_EFFORT",
            f"{model} does not support reasoning effort {effort!r}; one of {', '.join(allowed)}",
        )
    if re.match(r"gemini-3\.1-flash(-lite)?-image", m):
        return {"thinkingLevel": effort.upper(), "includeThoughts": True}
    if m == "gemini-3.7-flash-tiered":
        return {"thinkingLevel": effort.upper()}
    if not allowed:
        return None
    if m.startswith("claude-"):
        budget = 1024
    elif m.startswith("gpt-oss-"):
        budget = 8192
    elif m.startswith("gemini-3.1-pro") or m == "gemini-pro-agent":
        budget = 10001 if effort == "high" else 1001
    elif m.startswith("gemini-3.5-flash") or m == "gemini-3-flash-agent":
        budget = {"high": 10000, "medium": 4000}.get(effort, 1000)
    else:
        budget = {"high": -1, "medium": 4000}.get(effort, 1000)
    if max_tokens is not None and budget > 0 and max_tokens <= budget:
        raise LlmError("UNSUPPORTED_REASONING_EFFORT", f"maxTokens must exceed the thinking budget ({budget})")
    return {"includeThoughts": True, "thinkingBudget": budget}


# ---------------------------------------------------------------------- tool schemas
def _resolve_refs(schema: Any, root: dict[str, Any], seen: tuple[str, ...] = ()) -> Any:
    if isinstance(schema, dict):
        if "$ref" in schema:
            ref = schema["$ref"]
            if not isinstance(ref, str) or not ref.startswith("#/"):
                raise LlmError("INVALID_TOOL_SCHEMA", f"unsupported $ref {ref!r}")
            if ref in seen:
                raise LlmError("INVALID_TOOL_SCHEMA", f"cyclic $ref {ref!r}")
            target: Any = root
            for part in ref[2:].split("/"):
                target = target[part]
            return {**_resolve_refs(target, root, (*seen, ref)), **{k: v for k, v in schema.items() if k != "$ref"}}
        return {
            k: _resolve_refs(v, root, seen)
            for k, v in schema.items()
            if k not in ("$schema", "$id", "$defs", "definitions")
        }
    if isinstance(schema, list):
        return [_resolve_refs(v, root, seen) for v in schema]
    return schema


def gemini_schema(parameters: dict[str, Any]) -> dict[str, Any]:
    out = _resolve_refs(copy.deepcopy(parameters), parameters)
    if isinstance(out, dict):
        out.setdefault("type", "object")
    return out


def simple_schema(schema: Any) -> Any:
    """
    The reduced schema Claude / gpt-oss models accept: type, description, properties, required, items,
    string enums.
    """
    if not isinstance(schema, dict):
        return schema
    s = copy.deepcopy(schema)
    if "allOf" in s:
        merged: dict[str, Any] = {}
        for part in s.pop("allOf"):
            if isinstance(part, dict):
                for k, v in part.items():
                    if k == "properties":
                        merged.setdefault("properties", {}).update(v)
                    elif k == "required":
                        merged["required"] = sorted(set(merged.get("required", [])) | set(v))
                    else:
                        merged.setdefault(k, v)
        s = {**merged, **s}
    for key in ("anyOf", "oneOf"):
        if key in s:
            variants = [v for v in s.pop(key) if isinstance(v, dict) and v.get("type") != "null"]
            if variants:
                base = variants[0]
                for other in variants[1:]:
                    if base.get("type") != other.get("type"):
                        base = {k: v for k, v in base.items() if k != "type"}
                        break
                s = {
                    **base,
                    **{k: v for k, v in s.items() if k != "type"},
                    **({"type": base["type"]} if "type" in base else {}),
                }
    t = s.get("type")
    if isinstance(t, list):
        t = [x for x in t if x != "null"]
        t = t[0] if len(t) == 1 else (t or None)
    if t in ("integer", "number"):
        t = "number"
    out: dict[str, Any] = {}
    if t:
        out["type"] = t
    for key in ("description", "required"):
        if key in s:
            out[key] = s[key]
    if "properties" in s and isinstance(s["properties"], dict):
        out["properties"] = {k: simple_schema(v) for k, v in s["properties"].items()}
    if "items" in s:
        out["items"] = simple_schema(s["items"])
    if "enum" in s and all(isinstance(v, str) for v in s["enum"]):
        out["enum"] = list(s["enum"])
    return out


def function_declarations(tools: list[Any], model: str) -> list[dict[str, Any]]:
    simple = model.lower().startswith(("claude-", "gpt-oss-"))
    out = []
    for tool in tools:
        spec = convert_to_openai_tool(tool)["function"]
        params = spec.get("parameters") or {"type": "object", "properties": {}}
        decl: dict[str, Any] = {"name": spec["name"], "description": spec.get("description") or ""}
        if simple:
            decl["parameters"] = simple_schema(params)
        else:
            decl["parametersJsonSchema"] = gemini_schema(params)
        out.append(decl)
    return out


# ---------------------------------------------------------------------- contents
def _parse_args(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    try:
        data = json.loads(raw) if isinstance(raw, str) else {}
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def to_contents(messages: list[BaseMessage], model: str) -> tuple[str | None, list[dict[str, Any]]]:
    """
    ``(system_instruction, contents)``; consecutive same-role messages merge; tool results become
    ``functionResponse`` parts in a user turn.
    """
    system: list[str] = []
    contents: list[dict[str, Any]] = []
    call_names: dict[str, str] = {}
    gemini3 = model.lower().startswith("gemini-3")

    def push(role: str, parts: list[dict[str, Any]]) -> None:
        if not parts:
            return
        if contents and contents[-1]["role"] == role:
            contents[-1]["parts"].extend(parts)
        else:
            contents.append({"role": role, "parts": parts})

    for message in messages:
        if isinstance(message, SystemMessage):
            system.append(_text_of(message.content))
        elif isinstance(message, HumanMessage):
            parts: list[dict[str, Any]] = []
            text = _text_of(message.content)
            if text or not _images_of(message.content):
                parts.append({"text": text or "."})
            for url in _images_of(message.content):
                if url.startswith("data:") and ";base64," in url:
                    mime, data = url[5:].split(";base64,", 1)
                    parts.append({"inlineData": {"mimeType": mime, "data": data}})
            push("user", parts)
        elif isinstance(message, AIMessage):
            parts = []
            text = _text_of(message.content)
            if text:
                parts.append({"text": text})
            for i, call in enumerate(message.tool_calls or []):
                cid = str(call.get("id") or "")
                call_names[cid] = str(call.get("name") or "")
                part: dict[str, Any] = {
                    "functionCall": {"id": cid, "name": call.get("name"), "args": call.get("args") or {}}
                }
                if gemini3 and i == 0:
                    part["thoughtSignature"] = "skip_thought_signature_validator"
                parts.append(part)
            push("model", parts)
        elif isinstance(message, ToolMessage):
            cid = str(message.tool_call_id or "")
            text = _text_of(message.content)
            try:
                parsed = json.loads(text) if text else None
            except ValueError:
                parsed = None
            response = parsed if isinstance(parsed, dict) else {"output": text}
            if getattr(message, "status", None) == "error":
                response = {"output": text, "isError": True}
            push("user", [{"functionResponse": {"id": cid, "name": call_names.get(cid, "tool"), "response": response}}])
    return ("\n\n".join(s for s in system if s) or None), contents


def build_request(
    *,
    project: str,
    model: str,
    session_id: str,
    messages: list[BaseMessage],
    tools: list[Any],
    max_tokens: int | None,
    effort: str | None,
    temperature: float | None = None,
) -> dict[str, Any]:
    system, contents = to_contents(messages, model)
    request: dict[str, Any] = {"contents": contents, "sessionId": session_id}
    if system:
        request["systemInstruction"] = {"parts": [{"text": system}]}
    image_model = "-image" in model.lower()
    if tools and not image_model:
        request["tools"] = [{"functionDeclarations": function_declarations(tools, model)}]
        request["toolConfig"] = {
            "functionCallingConfig": {"mode": "VALIDATED" if model.lower().startswith("claude-") else "AUTO"}
        }
    generation: dict[str, Any] = {}
    if image_model:
        generation["responseModalities"] = ["TEXT", "IMAGE"]
    if max_tokens:
        generation["maxOutputTokens"] = (
            min(max_tokens, 64000) if model.lower().startswith("claude-") and max_tokens >= 65535 else max_tokens
        )
    if temperature is not None:
        generation["temperature"] = temperature
    thinking = thinking_config(model, effort, max_tokens)
    if thinking:
        generation["thinkingConfig"] = thinking
    if generation:
        request["generationConfig"] = generation
    return {
        "project": project,
        "requestId": f"agent/{int(time.time() * 1000)}/{uuid.uuid4()}/4",
        "model": model,
        "userAgent": "antigravity",
        "requestType": "agent",
        "request": request,
    }


# ---------------------------------------------------------------------- streaming translation
class AntigravityTranslator:
    def __init__(self, label: str) -> None:
        self.label = label
        self.saw_content = False
        self.saw_call = False
        self.finished = False
        self.calls = 0
        self.images: list[tuple[str, str]] = []  # (mime, base64)

    def feed(self, data: str) -> Iterator[AIMessageChunk]:
        if data == "[DONE]":
            return
        try:
            payload = json.loads(data)
        except ValueError:
            return
        if isinstance(payload, dict) and payload.get("error"):
            err = payload["error"]
            code = int(err.get("code") or 0) if isinstance(err, dict) else 0
            message = str(err.get("message") if isinstance(err, dict) else err)
            raise LlmError("RATE_LIMIT" if code == 429 else "SERVER", f"{self.label}: {message}")
        response = payload.get("response") if isinstance(payload, dict) and "response" in payload else payload
        if not isinstance(response, dict):
            return
        for candidate in response.get("candidates") or []:
            for part in (candidate.get("content") or {}).get("parts") or []:
                if not isinstance(part, dict):
                    continue
                if part.get("thought") and part.get("text"):
                    self.saw_content = True
                    yield AIMessageChunk(content="", additional_kwargs={"reasoning_content": str(part["text"])})
                elif part.get("text"):
                    text = str(part["text"])
                    if not self.saw_content and UNSUPPORTED_CLIENT.match(text):
                        notice = text.strip()[:200]
                        raise LlmError(UNSUPPORTED_CLIENT_CODE, f"Antigravity rejected the client signature: {notice}")
                    self.saw_content = True
                    yield AIMessageChunk(content=text)
                elif part.get("inlineData"):
                    inline = part["inlineData"]
                    self.saw_content = True
                    self.images.append((str(inline.get("mimeType") or "image/png"), str(inline.get("data") or "")))
                    yield AIMessageChunk(
                        content=[
                            {
                                "type": "image",
                                "mime_type": str(inline.get("mimeType") or "image/png"),
                                "data": str(inline.get("data") or ""),
                                "source_type": "base64",
                            }
                        ]
                    )
                elif part.get("functionCall"):
                    call = part["functionCall"]
                    self.saw_call = True
                    idx = self.calls
                    self.calls += 1
                    cid = str(call.get("id") or f"call_{uuid.uuid4().hex}")
                    yield AIMessageChunk(
                        content="",
                        tool_call_chunks=[
                            {
                                "name": str(call.get("name") or ""),
                                "args": json.dumps(call.get("args") or {}, ensure_ascii=False),
                                "id": cid,
                                "index": idx,
                                "type": "tool_call_chunk",
                            }
                        ],
                    )
            reason = candidate.get("finishReason")
            if reason:
                self.finished = True
                usage = response.get("usageMetadata") or {}
                prompt = int(usage.get("promptTokenCount") or 0)
                cached = int(usage.get("cachedContentTokenCount") or 0)
                out = int(usage.get("candidatesTokenCount") or 0)
                thoughts = int(usage.get("thoughtsTokenCount") or 0)
                meta: dict[str, Any] = {"input_tokens": prompt, "output_tokens": out, "total_tokens": prompt + out}
                if cached:
                    meta["input_token_details"] = {"cache_read": cached}
                if thoughts:
                    meta["output_token_details"] = {"reasoning": thoughts}
                if reason in ("SAFETY", "RECITATION", "BLOCKLIST"):
                    raise LlmError("CONTENT_FILTER", f"{self.label}: response blocked ({reason})")
                finish = "length" if reason == "MAX_TOKENS" else "tool_calls" if self.saw_call else "stop"
                yield AIMessageChunk(content="", response_metadata={"finish_reason": finish}, usage_metadata=meta)
                if not self.saw_content and not self.saw_call:
                    raise LlmError("EMPTY_RESPONSE", f"{self.label} returned no content")
