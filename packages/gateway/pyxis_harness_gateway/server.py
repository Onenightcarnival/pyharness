from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse

from pyxis_harness import package_toml

from . import anthropic_messages, openai_chat, openai_responses
from .chunks import BlockAssembler, Chunk, finish_failure, full_usage, is_content_delta
from .drafts import GatewayError, Generation, ParsedRequest, materialize
from .keys import KeyStore, presented_key
from .models import ModelCatalog, ModelResolutionError, Target
from .usage import UsageStore

_CFG = package_toml(__file__)["server"]
PROTOCOL_PATHS: dict[str, str] = dict(_CFG["PROTOCOL_PATHS"])
CORS_HEADERS: dict[str, str] = dict(_CFG["CORS_HEADERS"])
JSON_HEADERS = {"cache-control": "no-store", **CORS_HEADERS}
SSE_HEADERS = {"cache-control": "no-store", "connection": "keep-alive", "x-accel-buffering": "no", **CORS_HEADERS}
METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"]
CLIENT_CLOSED = {"status": 499, "code": "client_closed_request", "message": "the client closed the connection"}

PARSERS: dict[str, Callable[[Any], ParsedRequest]] = {
    "chat": openai_chat.parse_request,
    "responses": openai_responses.parse_request,
    "messages": anthropic_messages.parse_request,
}
COMPLETIONS: dict[str, Callable[..., dict[str, Any]]] = {
    "chat": openai_chat.completion,
    "responses": openai_responses.completion,
    "messages": anthropic_messages.message,
}


@dataclass
class GatewayDeps:
    """
    ``generate(generation)`` yields the chunks of one model request; ``load_image`` turns a pending image into a
    ``data:`` URL.
    """

    generate: Callable[[Generation], AsyncIterator[Chunk]]
    catalog: ModelCatalog
    keys: KeyStore
    usage: UsageStore
    load_image: Callable[[dict[str, Any]], Awaitable[str]]
    max_body_bytes: int
    logger: logging.Logger


def now_ms() -> int:
    return int(time.time() * 1000)


def describe_failure(error: BaseException) -> dict[str, Any]:
    """Status, code, message and parameter of a failure raised while serving a request."""
    if isinstance(error, GatewayError):
        return {"status": error.status, "code": error.code, "message": str(error), "param": error.param}
    if isinstance(error, ModelResolutionError):
        return {"status": 404, "code": "model_not_found", "message": str(error), "param": "model"}
    if isinstance(error, asyncio.CancelledError):
        return dict(CLIENT_CLOSED)
    return {"status": 500, "code": "internal_error", "message": str(error) or type(error).__name__}


def error_body(protocol: str, failure: dict[str, Any], anthropic_shape: bool = False) -> dict[str, Any]:
    if protocol == "messages" or (protocol == "models" and anthropic_shape):
        return anthropic_messages.error_body(failure["code"], failure["message"])
    if protocol == "responses":
        return openai_responses.error_body(failure["code"], failure["message"], failure.get("param"))
    return openai_chat.error_body(failure["code"], failure["message"], failure.get("param"))


def _json(status: int, body: Any, **headers: str) -> JSONResponse:
    return JSONResponse(body, status_code=status, headers={**JSON_HEADERS, **headers})


def _failed(protocol: str, failure: dict[str, Any], anthropic_shape: bool = False) -> JSONResponse:
    return _json(failure["status"], error_body(protocol, failure, anthropic_shape))


def _encoder(protocol: str, model_id: str, include_usage: bool) -> Any:
    if protocol == "chat":
        return openai_chat.ChatStreamEncoder(model_id, include_usage)
    if protocol == "responses":
        return openai_responses.ResponsesStreamEncoder(model_id)
    return anthropic_messages.AnthropicStreamEncoder(model_id)


async def _read_body(request: Request, limit: int) -> Any:
    data = bytearray()
    async for part in request.stream():
        data += part
        if len(data) > limit:
            raise GatewayError(413, "request_too_large", f"request body exceeds {limit} bytes")
    if not data.strip():
        raise GatewayError(400, "invalid_request_error", "request body is empty")
    try:
        return json.loads(data)
    except ValueError as exc:
        raise GatewayError(400, "invalid_request_error", "request body is not valid JSON") from exc


def _models(models: list[dict[str, str]], anthropic_shape: bool) -> dict[str, Any]:
    created = int(time.time())
    if not anthropic_shape:
        rows = [{"id": m["id"], "object": "model", "created": created, "owned_by": m["provider"]} for m in models]
        return {"object": "list", "data": rows}
    stamp = datetime.fromtimestamp(created, UTC).isoformat().replace("+00:00", "Z")
    rows = [{"id": m["id"], "type": "model", "display_name": m["name"], "created_at": stamp} for m in models]
    ids = [m["id"] for m in models]
    return {"data": rows, "has_more": False, "first_id": ids[0] if ids else None, "last_id": ids[-1] if ids else None}


async def _disconnected(request: Request) -> None:
    """Return once the client has closed the connection; the request body is already consumed."""
    while (await request.receive())["type"] != "http.disconnect":
        pass


class _Call:
    """One authenticated protocol request: its progress and the ledger row written when it ends."""

    def __init__(self, deps: GatewayDeps, protocol: str, key: dict[str, Any]) -> None:
        self.deps = deps
        self.protocol = protocol
        self.key = key
        self.started = now_ms()
        self.parsed: ParsedRequest | None = None
        self.target: Target | None = None
        self.usage: dict[str, int] | None = None
        self.finish: dict[str, Any] | None = None
        self.ttft: int | None = None
        self.failure: dict[str, Any] | None = None

    def observe(self, chunk: Chunk) -> None:
        if self.ttft is None and is_content_delta(chunk):
            self.ttft = now_ms() - self.started
        if chunk["type"] == "usage":
            self.usage = chunk["usage"]
        elif chunk["type"] == "finish":
            self.finish = chunk["reason"]
            self.failure = finish_failure(chunk["reason"]) or self.failure

    def record(self) -> None:
        counted = full_usage(self.usage)
        target, parsed = self.target, self.parsed
        try:
            self.deps.usage.record(
                {
                    "time": self.started,
                    "keyId": self.key["id"],
                    "keyName": self.key["name"],
                    "protocol": self.protocol,
                    "provider": target.provider if target else "",
                    "model": target.model if target else "",
                    "modelId": target.id if target else (parsed.model or "" if parsed else ""),
                    "stream": bool(parsed and parsed.stream),
                    "inputTokens": counted["input_tokens"],
                    "outputTokens": counted["output_tokens"],
                    "cacheReadTokens": counted["cache_read_tokens"],
                    "cacheWriteTokens": counted["cache_write_tokens"],
                    "reasoningTokens": counted["reasoning_tokens"],
                    "ttftMs": self.ttft,
                    "durationMs": now_ms() - self.started,
                    "status": self.failure["status"] if self.failure else 200,
                    "errorCode": self.failure["code"] if self.failure else None,
                }
            )
            self.deps.keys.touch(self.key["id"])
        except Exception as exc:  # noqa: BLE001  # the ledger never fails a served request
            self.deps.logger.warning("gateway: usage record failed: %s", exc)

    async def prepare(self, request: Request) -> Generation:
        """Parse the body, resolve the model against the key's allowlist and build the model request."""
        self.parsed = PARSERS[self.protocol](await _read_body(request, self.deps.max_body_bytes))
        self.target = self.deps.catalog.resolve(self.parsed.model)
        allowed = self.key["models"]
        if allowed is not None and self.target.id not in allowed:
            code = "permission_error" if self.protocol == "messages" else "model_not_allowed"
            raise GatewayError(403, code, f'this API key may not use model "{self.target.id}"', "model")
        return await materialize(self.parsed, self.target, self.deps.load_image)

    async def frames(self, generation: Generation) -> AsyncIterator[str]:
        """SSE frames of a streamed request; the ledger row is written when the stream ends."""
        assert self.parsed is not None and self.target is not None
        encoder = _encoder(self.protocol, self.target.id, self.parsed.include_usage)
        try:
            async for frame in self._relay(encoder, generation):
                if frame:
                    yield frame
        except asyncio.CancelledError:
            self.failure = dict(CLIENT_CLOSED)
            raise
        except Exception as exc:  # noqa: BLE001
            self.failure = describe_failure(exc)
            yield encoder.fail(self.failure) + encoder.end()
        finally:
            self.record()

    async def _relay(self, encoder: Any, generation: Generation) -> AsyncIterator[str]:
        yield encoder.start()
        async for chunk in self.deps.generate(generation):
            self.observe(chunk)
            yield encoder.push(chunk)
        if self.finish is None:
            yield encoder.push({"type": "finish", "reason": {"kind": "stop"}})
        yield encoder.end()

    async def complete(self, generation: Generation) -> JSONResponse:
        """The complete object of a non-streamed request."""
        assert self.target is not None
        assembler = BlockAssembler()
        async for chunk in self.deps.generate(generation):
            self.observe(chunk)
            assembler.push(chunk)
        if self.failure is not None:
            return _failed(self.protocol, self.failure)
        reason = assembler.finish or {"kind": "stop"}
        return _json(200, COMPLETIONS[self.protocol](self.target.id, assembler.blocks(), assembler.usage, reason))


async def _serve(deps: GatewayDeps, protocol: str, key: dict[str, Any], request: Request) -> Response:
    call = _Call(deps, protocol, key)
    try:
        generation = await call.prepare(request)
        assert call.parsed is not None
        if call.parsed.stream:
            frames = call.frames(generation)
            return StreamingResponse(frames, media_type="text/event-stream; charset=utf-8", headers=SSE_HEADERS)
        work = asyncio.ensure_future(call.complete(generation))
        gone = asyncio.ensure_future(_disconnected(request))
        try:
            await asyncio.wait({work, gone}, return_when=asyncio.FIRST_COMPLETED)
        finally:
            for task in (work, gone):
                if not task.done():
                    task.cancel()
                    with contextlib.suppress(asyncio.CancelledError, Exception):
                        await task
        if work.cancelled():
            call.failure = dict(CLIENT_CLOSED)
            response: Response = Response(status_code=499, headers=CORS_HEADERS)
        else:
            response = work.result()
    except Exception as exc:  # noqa: BLE001
        call.failure = describe_failure(exc)
        response = _failed(protocol, call.failure)
    call.record()
    return response


def create_app(deps: GatewayDeps) -> FastAPI:
    """The gateway application; the caller serves it."""
    app = FastAPI(title="PyxisHarness gateway", docs_url=None, redoc_url=None, openapi_url=None)

    @app.api_route("/{path:path}", methods=METHODS)
    async def handle(request: Request) -> Response:
        path = request.url.path
        headers = request.headers
        anthropic_shape = "anthropic-version" in headers or "x-api-key" in headers
        if request.method == "OPTIONS":
            return Response(status_code=204, headers=CORS_HEADERS)
        protocol = "models" if path == "/v1/models" else PROTOCOL_PATHS.get(path)
        if protocol is None:
            missing = {"status": 404, "code": "not_found", "message": f"no route for {request.method} {path}"}
            return _failed("chat", missing, anthropic_shape)
        key = deps.keys.verify(presented_key(headers))
        if key is None:
            anthropic = protocol == "messages" or (protocol == "models" and anthropic_shape)
            code = "authentication_error" if anthropic else "invalid_api_key"
            denied = {"status": 401, "code": code, "message": "missing or invalid API key"}
            return _json(401, error_body(protocol, denied, anthropic_shape), **{"www-authenticate": "Bearer"})
        expected = "GET" if protocol == "models" else "POST"
        if request.method != expected:
            wrong = {"status": 405, "code": "method_not_allowed", "message": f"use {expected}"}
            return _failed(protocol, wrong, anthropic_shape)
        if protocol == "models":
            allowed = key["models"]
            models = [m for m in deps.catalog.list() if allowed is None or m["id"] in allowed]
            return _json(200, _models(models, anthropic_shape))
        return await _serve(deps, protocol, key, request)

    return app
