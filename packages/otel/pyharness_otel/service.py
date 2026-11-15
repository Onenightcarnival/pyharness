"""``OtelService``: configuration, the turn-end hook, the Observability status / settings / test routes."""

from __future__ import annotations

import asyncio
import base64
import json
import random
import re
import time
from pathlib import Path
from typing import Any, ClassVar

import httpx
from fastapi import APIRouter, HTTPException, Request
from opentelemetry.trace import SpanKind

from pyharness import Service, manage

from .config import SECRET_REF, Config
from .pipeline import Pipeline
from .spans import build_turn_spans


# ---------------------------------------------------------------------- service
class OtelService(Service):
    """Turn traces to an OTLP backend; the Observability settings page."""

    key = "otel"
    name = "pyharness-otel"
    inject: ClassVar[list[str]] = ["http", "webui"]
    Config = Config

    def __init__(self, ctx: Any, config: Config) -> None:
        super().__init__(ctx, config)
        self.pipeline: Pipeline | None = None
        self.last_error: str | None = None
        self.exporter_factory: Any = None  # tests inject an in-memory exporter

    # ------------------------------------------------------------------ lifecycle
    async def start(self) -> None:
        self.ctx.on("agent/turn-end", self._on_turn_end)
        self.ctx.http.include_router(self._router(), prefix="/api/otel", tags=["pyharness-otel"])
        self.ctx.webui.register_client(Path(__file__).with_name("client.js"))
        self.apply()

    async def stop(self) -> None:
        if self.pipeline is not None:
            await asyncio.to_thread(self.pipeline.shutdown)
            self.pipeline = None

    def secret(self) -> str:
        profile = self.ctx.get("profile", None)
        if profile is None or not hasattr(profile, "credentials"):
            return ""
        return profile.credentials.get(self.config.secret_key or SECRET_REF) or ""

    def apply(self) -> None:
        """(Re)start the pipeline from the current configuration; disabled or without an endpoint it stays down."""
        if self.pipeline is not None:
            self.pipeline.shutdown()
            self.pipeline = None
        self.last_error = None
        if not self.config.enabled or not self.config.endpoint.strip():
            return
        try:
            exporter = self.exporter_factory() if self.exporter_factory else None
            self.pipeline = Pipeline(self.config, self.secret(), exporter=exporter)
        except Exception as exc:  # noqa: BLE001
            self.last_error = f"{type(exc).__name__}: {exc}"
            self.ctx.logger.warning("otel pipeline not started: %s", exc)

    # ------------------------------------------------------------------ turns
    async def _on_turn_end(self, turn: Any) -> None:
        if self.pipeline is None:
            return
        record = (getattr(turn, "extras", None) or {}).get("turn")
        if not record:
            return
        try:
            agents = self.ctx.get("agents", None)
            session = await agents.get_session(turn.session_id) if agents is not None else None
            handle = agents.current_run(turn.session_id) if agents is not None else None
            events = list(handle.events) if handle is not None else []
            system_prompt = tool_defs = None
            if self.config.capture_content:
                prompt = self.ctx.get("prompt", None)
                system_prompt = prompt.render((session or {}).get("preset")) if prompt is not None else None
                tools = self.ctx.get("tools", None)
                tool_defs = (
                    [
                        {
                            "type": "function",
                            "name": t.name,
                            "description": t.description or None,
                            "parameters": t.tool_call_schema.model_json_schema()
                            if hasattr(t, "tool_call_schema")
                            else {},
                        }
                        for t in tools.list()
                    ]
                    if tools is not None
                    else None
                )
            await asyncio.to_thread(
                build_turn_spans,
                self.pipeline.tracer,
                record,
                session=session,
                events=events,
                capture=self.config.capture_content,
                limit=self.config.content_max_chars,
                system_prompt=system_prompt,
                tool_defs=tool_defs,
                user_input=turn.input,
            )
        except Exception as exc:  # noqa: BLE001
            self.last_error = f"{type(exc).__name__}: {exc}"
            self.ctx.logger.warning("otel turn export failed: %s", exc)

    # ------------------------------------------------------------------ views
    def status(self) -> dict[str, Any]:
        p = self.pipeline
        out: dict[str, Any] = {
            "configured": bool(self.config.endpoint.strip()),
            "enabled": self.config.enabled,
            "endpoint": self.config.endpoint,
            "publicKey": self.config.public_key,
            "secretKeySet": bool(self.secret()),
            "captureContent": self.config.capture_content,
            "gzip": self.config.gzip,
            "contentMaxChars": self.config.content_max_chars,
            "maxExportBatchSize": self.config.max_export_batch_size,
            "running": p is not None,
            "exportedBatches": p.exporter.batches if p else 0,
            "exportedSpans": p.exporter.spans if p else 0,
            "version": "0.1.0",
        }
        if p is not None:
            out["traceEndpoint"] = p.trace_endpoint
            out["langfuse"] = p.langfuse
            if p.exporter.last_at:
                out["lastExportAt"] = p.exporter.last_at
                out["lastExportOk"] = p.exporter.last_ok
            if p.exporter.last_error:
                out["lastExportError"] = p.exporter.last_error
        if self.last_error:
            out["lastError"] = self.last_error
        return out

    async def save(self, data: dict[str, Any]) -> dict[str, Any]:
        profile = self.ctx.get("profile", None)
        if profile is None:
            raise HTTPException(503, "no profile")
        fields: dict[str, Any] = {}
        for key, name in (("endpoint", "endpoint"), ("publicKey", "public_key")):
            if key in data and data[key] is not None:
                fields[name] = str(data[key]).strip()
        for key, name in (("enabled", "enabled"), ("captureContent", "capture_content"), ("gzip", "gzip")):
            if isinstance(data.get(key), bool):
                fields[name] = data[key]
        for key, name, lo, hi in (
            ("contentMaxChars", "content_max_chars", 100, 10_000_000),
            ("maxExportBatchSize", "max_export_batch_size", 1, 4096),
        ):
            value = data.get(key)
            if value is None:
                fields[name] = Config.model_fields[name].default
            elif isinstance(value, int) and not isinstance(value, bool) and lo <= value <= hi:
                fields[name] = value
            else:
                raise HTTPException(400, f"{key} must be an integer from {lo} to {hi}")
        if (
            fields.get("enabled", self.config.enabled)
            and not (fields.get("endpoint", self.config.endpoint) or "").strip()
        ):
            raise HTTPException(400, "endpoint is required")
        if "secretKey" in data and data["secretKey"] is not None:
            ref = self.config.secret_key or SECRET_REF
            if data["secretKey"] == "":
                profile.credentials.delete(ref)
            else:
                profile.credentials.set(ref, str(data["secretKey"]))
        result = await manage.set_entry_config(profile, "otel", fields, merge=True, preflight=False)
        if result.get("application") == "rejected":
            raise HTTPException(422, result.get("error") or "rejected")
        for name, value in fields.items():
            setattr(self.config, name, value)
        self.apply()
        return self.status()

    async def test(self, data: dict[str, Any]) -> dict[str, Any]:
        """
        Send test spans through a temporary pipeline built from ``data`` (or the saved settings); verify on
        Langfuse.
        """
        config = self.config.model_copy()
        if data.get("endpoint"):
            config.endpoint = str(data["endpoint"])
        if data.get("publicKey") is not None:
            config.public_key = str(data["publicKey"])
        if isinstance(data.get("gzip"), bool):
            config.gzip = data["gzip"]
        secret = str(data["secretKey"]) if data.get("secretKey") else self.secret()
        if not config.endpoint.strip():
            raise HTTPException(400, "endpoint is required")
        config.trace_export_interval_ms = 500
        pipeline = Pipeline(config, secret, exporter=self.exporter_factory() if self.exporter_factory else None)
        trace_ids: list[str] = []
        notes: list[str] = []
        try:
            tracer = pipeline.tracer
            with tracer.start_as_current_span(
                "pyharness-otel connection test", kind=SpanKind.INTERNAL, attributes={"pyharness.otel.test": True}
            ) as s1:
                trace_ids.append(format(s1.get_span_context().trace_id, "032x"))
            if not await asyncio.to_thread(pipeline.flush):
                raise HTTPException(502, "connectivity test: export did not complete")
            if pipeline.exporter.last_ok is False:
                raise HTTPException(502, f"connectivity test failed: {pipeline.exporter.last_error}")
            payload = base64.b64encode(random.randbytes(600 * 1024)).decode()
            with tracer.start_as_current_span(
                "pyharness-otel payload test",
                attributes={"pyharness.otel.test": True, "pyharness.otel.test.payload": payload},
            ) as s2:
                trace_ids.append(format(s2.get_span_context().trace_id, "032x"))
            await asyncio.to_thread(pipeline.flush)
            if pipeline.exporter.last_ok is False:
                raise HTTPException(
                    502,
                    f"payload test (900 KB) failed: {pipeline.exporter.last_error}; "
                    "the backend may cap the request size",
                )
            now = time.time()
            turn = {
                "session_id": "otel-test",
                "seq": 1,
                "outcome": "completed",
                "model": "deepseek:deepseek-chat",
                "at": now - 1.2,
                "stats": {
                    "steps": 1,
                    "input_tokens": 12,
                    "output_tokens": 5,
                    "ttft_ms": 120,
                    "ttft_steps": 1,
                    "duration_ms": 1200,
                },
                "records": [
                    {"t": "user", "at": now - 1.2},
                    {
                        "t": "step",
                        "at": now - 1.1,
                        "dur_ms": 900,
                        "ttft_ms": 120,
                        "tool_calls": 0,
                        "input_tokens": 12,
                        "output_tokens": 5,
                    },
                    {"t": "end", "at": now, "outcome": "completed"},
                ],
            }
            tid = await asyncio.to_thread(
                build_turn_spans,
                tracer,
                turn,
                session={"preset": "standard"},
                events=[{"type": "token", "text": "pong"}],
                capture=True,
                limit=config.content_max_chars,
                system_prompt="test",
                tool_defs=[],
                user_input="ping",
            )
            if tid:
                trace_ids.append(tid)
            await asyncio.to_thread(pipeline.flush)
            if pipeline.exporter.last_ok is False:
                raise HTTPException(502, f"GenAI test failed: {pipeline.exporter.last_error}")
            notes.append(
                "Tests passed: connectivity, 900 KB payload, GenAI turn "
                f"({pipeline.exporter.spans} spans{', gzip' if config.gzip else ''})."
            )
            found: dict[str, bool] = {}
            if pipeline.langfuse:
                found = await self._verify_on_langfuse(pipeline, trace_ids, attempts=6, delay=4.0)
                missing = [t for t, ok in found.items() if not ok]
                notes.append(
                    "All test traces were stored."
                    if not missing
                    else f"{len(missing)} of {len(found)} test traces were not found yet (server-side drop or delay)."
                )
        finally:
            await asyncio.to_thread(pipeline.shutdown)
        return {
            "ok": True,
            "message": " ".join(notes),
            "traceIds": trace_ids,
            "found": found,
            "traceEndpoint": pipeline.trace_endpoint,
        }

    async def _verify_on_langfuse(
        self, pipeline: Pipeline, trace_ids: list[str], *, attempts: int, delay: float
    ) -> dict[str, bool]:
        base = re.sub(r"/api/public/otel.*$", "", pipeline.endpoint)
        found = dict.fromkeys(trace_ids, False)
        async with httpx.AsyncClient(headers=pipeline.headers, timeout=8.0) as client:
            for _ in range(attempts):
                for tid in [t for t, ok in found.items() if not ok]:
                    try:
                        res = await client.get(f"{base}/api/public/traces/{tid}")
                        if res.status_code == 200:
                            found[tid] = True
                    except httpx.HTTPError:
                        pass
                if all(found.values()):
                    break
                await asyncio.sleep(delay)
        return found

    async def verify_recent(self) -> dict[str, Any]:
        p = self.pipeline
        if p is None:
            raise HTTPException(409, "not configured or not running")
        if not p.langfuse:
            raise HTTPException(409, "verification works with Langfuse endpoints only")
        recent = list(p.exporter.trace_ids)[-8:]
        if not recent:
            raise HTTPException(409, "no exports yet in this run")
        found = await self._verify_on_langfuse(p, recent, attempts=2, delay=5.0)
        return {
            "ok": all(found.values()),
            "found": found,
            "message": "Recent exports found." if all(found.values()) else "Some exports were not found.",
        }

    # ------------------------------------------------------------------ routes
    def _router(self) -> APIRouter:
        router = APIRouter()
        service = self

        async def body(request: Request) -> dict[str, Any]:
            raw = await request.body()
            try:
                data = json.loads(raw) if raw else {}
            except ValueError:
                data = None
            if not isinstance(data, dict):
                raise HTTPException(400, "invalid JSON body")
            return data

        @router.get("/status")
        async def status() -> dict[str, Any]:
            return service.status()

        @router.put("/settings")
        async def settings(request: Request) -> dict[str, Any]:
            return await service.save(await body(request))

        @router.post("/test")
        async def test(request: Request) -> dict[str, Any]:
            return await service.test(await body(request))

        @router.post("/verify")
        async def verify() -> dict[str, Any]:
            return await service.verify_recent()

        return router
