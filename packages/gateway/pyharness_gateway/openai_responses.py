"""
OpenAI Responses: request parsing, the semantic event stream and the complete response object.

| name                      | contract                                                                    |
|---------------------------|-----------------------------------------------------------------------------|
| ``parse_request()``       | body → ``ParsedRequest``; ``reasoning`` input items are dropped             |
| ``ResponsesStreamEncoder``| semantic events numbered by ``sequence_number``; one output item per block  |
| ``completion()``          | the ``response`` object of a finished generation                            |
| ``error_body()``          | ``{"error": {type, code, message, param}}``                                 |
"""

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
    text_block,
    text_of,
    tool_name,
    unsupported,
)

CLIENT_ERRORS = ("invalid_request_error", "unsupported_parameter")
TEXT_PARTS = ("input_text", "output_text", "text")
ITEM_PREFIX = {"message": "msg_", "reasoning": "rs_", "function_call": "fc_"}


def _parts(content: Any, param: str, allow_images: bool) -> list[Block]:
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
        kind = part.get("type")
        if kind in TEXT_PARTS:
            if not isinstance(part.get("text"), str):
                raise invalid(f'"{where}.text" must be a string', where)
            blocks.append(text_block(part["text"]))
        elif kind == "input_image" and allow_images:
            image = part.get("image_url")
            url = image if isinstance(image, str) else image.get("url") if is_record(image) else None
            if not isinstance(url, str) or not url:
                raise invalid(f'"{where}.image_url" must carry a URL', where)
            blocks.append(image_from_url(url))
        elif kind == "refusal":
            # Refusal text of an earlier turn is replayed as plain text.
            if isinstance(part.get("refusal"), str):
                blocks.append(text_block(part["refusal"]))
        else:
            raise unsupported(f"{where}.type={kind}")
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
        description = tool.get("description")
        tools.append(
            {
                "name": tool_name(tool.get("name"), f"{where}.name"),
                "description": description if isinstance(description, str) else "",
                "parameters": parameter_schema(tool.get("parameters"), f"{where}.parameters"),
            }
        )
    return tools


def _call_id(item: dict[str, Any], where: str) -> str:
    if not isinstance(item.get("call_id"), str) or not item["call_id"]:
        raise invalid(f'"{where}.call_id" must be a string', where)
    return item["call_id"]


def _item(item: Any, where: str, system: list[str], messages: list[Draft]) -> None:
    if not is_record(item):
        raise invalid(f'"{where}" must be an object', where)
    kind = item.get("type") or ("message" if item.get("role") is not None else None)
    if kind == "message":
        role = item.get("role")
        if role in ("system", "developer"):
            system.append(text_of(_parts(item.get("content"), f"{where}.content", False)))
        elif role == "user":
            messages.append({"role": "user", "content": _parts(item.get("content"), f"{where}.content", True)})
        elif role == "assistant":
            push_assistant(messages, _parts(item.get("content"), f"{where}.content", False))
        else:
            raise invalid(f'"{where}.role" must be system, developer, user or assistant', where)
    elif kind == "function_call":
        call = {
            "type": "tool-call",
            "id": _call_id(item, where),
            "name": tool_name(item.get("name"), f"{where}.name"),
            "arguments": arguments_text(item.get("arguments")),
        }
        push_assistant(messages, [call])
    elif kind == "function_call_output":
        output = item.get("output")
        content = [text_block(output)] if isinstance(output, str) else _parts(output, f"{where}.output", False)
        messages.append({"role": "tool", "call_id": _call_id(item, where), "content": content, "is_error": False})
    elif kind != "reasoning":
        raise unsupported(f"{where}.type={kind}")


def parse_request(body: Any) -> ParsedRequest:
    if not is_record(body):
        raise invalid("request body must be a JSON object")
    if body.get("previous_response_id") is not None:
        raise unsupported("previous_response_id")
    text = body.get("text") if is_record(body.get("text")) else {}
    text_format = text.get("format") if is_record(text.get("format")) else {}
    if text_format.get("type") not in (None, "text"):
        raise unsupported(f"text.format.type={text_format.get('type')}")
    system: list[str] = []
    instructions = optional_string(body.get("instructions"), "instructions")
    if instructions is not None:
        system.append(instructions)
    messages: list[Draft] = []
    if isinstance(body.get("input"), str):
        messages.append({"role": "user", "content": [text_block(body["input"])]})
    elif isinstance(body.get("input"), list):
        for index, item in enumerate(body["input"]):
            _item(item, f"input[{index}]", system, messages)
    else:
        raise invalid('"input" must be a string or a list of items', "input")
    declared = _tools(body.get("tools"))
    reasoning = body.get("reasoning") if is_record(body.get("reasoning")) else {}
    return ParsedRequest(
        model=optional_string(body.get("model"), "model"),
        stream=optional_boolean(body.get("stream"), "stream") or False,
        include_usage=True,
        system=join_system(system),
        messages=messages,
        tools=None if body.get("tool_choice") == "none" else declared,
        temperature=optional_number(body.get("temperature"), "temperature", 0, 2),
        max_tokens=optional_integer(body.get("max_output_tokens"), "max_output_tokens"),
        stop=None,
        reasoning_effort=optional_string(reasoning.get("effort"), "reasoning.effort"),
    )


def _usage(usage: dict[str, int] | None) -> dict[str, Any]:
    full = full_usage(usage)
    return {
        "input_tokens": full["input_tokens"],
        "input_tokens_details": {"cached_tokens": full["cache_read_tokens"]},
        "output_tokens": full["output_tokens"],
        "output_tokens_details": {"reasoning_tokens": full["reasoning_tokens"]},
        "total_tokens": full["total_tokens"],
    }


def error_body(code: str, message: str, param: str | None = None) -> dict[str, Any]:
    kind = "invalid_request_error" if code in CLIENT_ERRORS else "server_error"
    return {"error": {"type": kind, "code": code, "message": message, "param": param}}


def _text_part(text: str) -> dict[str, Any]:
    return {"type": "output_text", "text": text, "annotations": []}


def _finished(item_id: str, kind: str, text: str, call_id: str = "", name: str = "") -> dict[str, Any]:
    """A completed output item."""
    if kind == "message":
        return {
            "id": item_id,
            "type": "message",
            "status": "completed",
            "role": "assistant",
            "content": [_text_part(text)],
        }
    if kind == "reasoning":
        summary = [{"type": "summary_text", "text": text}] if text else []
        return {"id": item_id, "type": "reasoning", "summary": summary}
    return {
        "id": item_id,
        "type": "function_call",
        "status": "completed",
        "call_id": call_id,
        "name": name,
        "arguments": text,
    }


def output_of(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Output items of finished blocks, in block order."""
    output = []
    for block in blocks:
        if block["type"] == "text":
            output.append(_finished(request_id("msg_"), "message", block["text"]))
        elif block["type"] == "reasoning":
            output.append(_finished(request_id("rs_"), "reasoning", block["text"]))
        elif block["type"] == "tool-call":
            item_id = request_id("fc_")
            output.append(_finished(item_id, "function_call", block["arguments"], block["id"], block["name"]))
    return output


def _response(
    response_id: str,
    created: int,
    model: str,
    status: str,
    output: list[dict[str, Any]],
    usage: dict[str, int] | None,
    reason: dict[str, Any] | None,
) -> dict[str, Any]:
    truncated = reason is not None and reason["kind"] == "max-tokens"
    return {
        "id": response_id,
        "object": "response",
        "created_at": created,
        "status": status,
        "model": model,
        "output": output,
        "error": None,
        "incomplete_details": {"reason": "max_output_tokens"} if truncated else None,
        "usage": None if status == "in_progress" else _usage(usage),
    }


def completion(
    model: str, blocks: list[dict[str, Any]], usage: dict[str, int] | None, reason: dict[str, Any]
) -> dict[str, Any]:
    status = "incomplete" if reason["kind"] == "max-tokens" else "completed"
    return _response(request_id("resp_"), int(time.time()), model, status, output_of(blocks), usage, reason)


class ResponsesStreamEncoder:
    """Responses semantic events; an output item opens per block and closes at its end or at the finish."""

    def __init__(self, model: str) -> None:
        self.model = model
        self.id = request_id("resp_")
        self.created = int(time.time())
        self._items: dict[int, dict[str, Any]] = {}  # block index → open item
        self._done: dict[int, dict[str, Any]] = {}  # output index → finished item
        self._sequence = 0
        self._next_output = 0
        self._usage: dict[str, int] | None = None

    def _event(self, kind: str, **payload: Any) -> str:
        frame = sse({"type": kind, "sequence_number": self._sequence, **payload}, kind)
        self._sequence += 1
        return frame

    def _output(self) -> list[dict[str, Any]]:
        return [self._done[index] for index in sorted(self._done)]

    def _open(self, index: int, kind: str, call_id: str = "", name: str = "") -> str:
        item = {
            "output_index": self._next_output,
            "id": request_id(ITEM_PREFIX[kind]),
            "kind": kind,
            "text": "",
            "call_id": call_id,
            "name": name,
        }
        self._next_output += 1
        self._items[index] = item
        at = {"output_index": item["output_index"]}
        if kind == "message":
            added = {"id": item["id"], "type": "message", "status": "in_progress", "role": "assistant", "content": []}
            frames = self._event("response.output_item.added", item=added, **at)
            part = _text_part("")
            return frames + self._event(
                "response.content_part.added", item_id=item["id"], content_index=0, part=part, **at
            )
        if kind == "reasoning":
            return self._event(
                "response.output_item.added", item={"id": item["id"], "type": "reasoning", "summary": []}, **at
            )
        added = {
            "id": item["id"],
            "type": "function_call",
            "status": "in_progress",
            "call_id": call_id,
            "name": name,
            "arguments": "",
        }
        return self._event("response.output_item.added", item=added, **at)

    def _close(self, index: int) -> str:
        item = self._items.pop(index, None)
        if item is None:
            return ""
        at = {"item_id": item["id"], "output_index": item["output_index"]}
        text = item["text"]
        finished = _finished(item["id"], item["kind"], text, item["call_id"], item["name"])
        frames = ""
        if item["kind"] == "message":
            frames += self._event("response.output_text.done", content_index=0, text=text, **at)
            frames += self._event("response.content_part.done", content_index=0, part=_text_part(text), **at)
        elif item["kind"] == "reasoning":
            if text:
                frames += self._event("response.reasoning_summary_text.done", summary_index=0, text=text, **at)
        else:
            frames += self._event("response.function_call_arguments.done", arguments=text, **at)
        self._done[item["output_index"]] = finished
        return frames + self._event("response.output_item.done", output_index=item["output_index"], item=finished)

    def _delta(self, index: int, kind: str, event: str, text: str, **extra: Any) -> str:
        """Append ``text`` to the block's item, opening it first when the block start was not seen."""
        frames = "" if index in self._items else self._open(index, kind)
        item = self._items[index]
        item["text"] += text
        if text:
            frames += self._event(event, item_id=item["id"], output_index=item["output_index"], delta=text, **extra)
        return frames

    def start(self) -> str:
        response = _response(self.id, self.created, self.model, "in_progress", [], None, None)
        return self._event("response.created", response=response) + self._event(
            "response.in_progress", response=response
        )

    def push(self, chunk: Chunk) -> str:
        kind = chunk["type"]
        if kind == "block-start":
            item_kind = {"text": "message", "reasoning": "reasoning"}.get(chunk["block_type"])
            return self._open(chunk["index"], item_kind) if item_kind else ""
        if kind == "text-delta":
            return self._delta(chunk["index"], "message", "response.output_text.delta", chunk["text"], content_index=0)
        if kind == "reasoning-delta":
            event = "response.reasoning_summary_text.delta"
            return self._delta(chunk["index"], "reasoning", event, chunk["text"], summary_index=0)
        if kind == "tool-call-delta":
            index = chunk["index"]
            frames = ""
            if index not in self._items:
                frames = self._open(index, "function_call", chunk["id"], chunk.get("name", ""))
            elif chunk.get("name") and not self._items[index]["name"]:
                self._items[index]["name"] = chunk["name"]
            event = "response.function_call_arguments.delta"
            return frames + self._delta(index, "function_call", event, chunk["arguments_delta"])
        if kind == "block-end":
            return self._close(chunk["index"])
        if kind == "usage":
            self._usage = chunk["usage"]
            return ""
        if kind == "finish":
            reason = chunk["reason"]
            failure = finish_failure(reason)
            if failure is not None:
                return self.fail(failure)
            frames = "".join(self._close(index) for index in list(self._items))
            status = "incomplete" if reason["kind"] == "max-tokens" else "completed"
            response = _response(self.id, self.created, self.model, status, self._output(), self._usage, reason)
            return frames + self._event(f"response.{status}", response=response)
        return ""

    def end(self) -> str:
        return ""

    def fail(self, error: dict[str, Any]) -> str:
        response = _response(self.id, self.created, self.model, "failed", self._output(), self._usage, None)
        response["error"] = {"code": error["code"], "message": error["message"]}
        failed = self._event("response.failed", response=response)
        return failed + self._event("error", code=error["code"], message=error["message"], param=None)
