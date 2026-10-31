"""``ctx.otel``: OpenTelemetry export of agent turns (GenAI semantic conventions) to an OTLP/HTTP backend such as Langfuse.

| member        | contract                                                                  |
|---------------|---------------------------------------------------------------------------|
| ``status()``  | configuration (secret never returned), pipeline state, export counters    |
| ``save()``    | write the settings to the profile and restart the pipeline in place       |
| ``test()``    | send test spans (connectivity, payload, GenAI shape) and verify on Langfuse |

| config                   | meaning                                                              |
|--------------------------|----------------------------------------------------------------------|
| ``enabled``              | export turns (default off)                                           |
| ``endpoint``             | OTLP base URL; a Langfuse host gets ``/api/public/otel`` appended    |
| ``public_key``           | Basic-auth user (Langfuse ``pk-lf-…``)                               |
| ``secret_key``           | credential reference of the Basic-auth password (``OTEL_SECRET_KEY``) |
| ``capture_content``      | put messages, system prompt, tool definitions, arguments and results on spans |
| ``content_max_chars``    | per-attribute limit; longer values become ``{"truncated": true, …}`` |
| ``gzip``                 | compress OTLP requests                                               |
| ``max_export_batch_size``| spans per export request                                             |
| ``service_name``         | ``service.name`` resource attribute                                  |

One trace per turn: ``enter_ai_application_system`` (ENTRY) → ``invoke_agent <preset>`` (AGENT) → ``react step`` (STEP)
→ ``chat <model>`` (LLM) and ``execute_tool <name>`` (TOOL), built from the turn record after ``agent/turn-end``.
Attribute names follow the GenAI semantic conventions used by dsh-otel; Langfuse aliases (``langfuse.session.id``,
``langfuse.user.id``) ride along. Routes under ``/api/otel``: ``GET status``, ``PUT settings``, ``POST test``,
``POST verify``.
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import random
import re
import time
from collections import deque
from pathlib import Path
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from pyharness import Service

SECRET_REF = "OTEL_SECRET_KEY"
DEFAULT_SERVICE = "pyharness"
AGENT_SYSTEM = "pyharness"
LANGFUSE_RE = re.compile(r"langfuse", re.I)
FINISH = {"tool-calls": "tool_calls", "max-tokens": "length", "aborted": "cancelled", "stop": "stop", "error": "error"}


class Config(BaseModel):
    enabled: bool = False
    endpoint: str = ""
    public_key: str = ""
    secret_key: str | None = Field(SECRET_REF, description="Credential reference of the Basic-auth password.")
    capture_content: bool = True
    content_max_chars: int = Field(128000, ge=100, le=10_000_000)
    gzip: bool = False
    max_export_batch_size: int = Field(512, ge=1, le=4096)
    max_queue_size: int = 2048
    trace_export_interval_ms: int = 5000
    export_timeout_ms: int = 30000
    service_name: str = DEFAULT_SERVICE


# ---------------------------------------------------------------------- endpoint helpers
def normalize_endpoint(raw: str, langfuse_hint: bool = False) -> str:
    url = (raw or "").strip().rstrip("/")
    if not url:
        return ""
    if not re.match(r"^[a-z][a-z0-9+.-]*://", url, re.I):
        url = "https://" + url
    if (LANGFUSE_RE.search(url) or langfuse_hint) and not re.search(r"/api/public/otel$|/v1/(traces|metrics)$", url):
        url += "/api/public/otel"
    return url


def is_langfuse_key_pair(public_key: str, secret: str) -> bool:
    return public_key.startswith("pk-lf-") and secret.startswith("sk-lf-")


def is_langfuse_endpoint(url: str) -> bool:
    return bool(LANGFUSE_RE.search(url)) or "/api/public/otel" in url


def signal_url(base: str, signal: str) -> str:
    if re.search(r"/v1/(traces|metrics)$", base):
        return re.sub(r"/v1/(traces|metrics)$", f"/v1/{signal}", base)
    return f"{base}/v1/{signal}"


def basic_auth(public_key: str, secret: str) -> dict[str, str]:
    pk, sk = public_key.strip(), secret.strip()
    if not pk and not sk:
        return {}
    return {"authorization": "Basic " + base64.b64encode(f"{pk}:{sk}".encode()).decode()}


# ---------------------------------------------------------------------- pipeline
class CountingExporter:
    """Wraps the OTLP exporter: batches / spans / last result and the last trace ids, for the status page."""

    def __init__(self, inner: Any) -> None:
        self.inner = inner
        self.batches = 0
        self.spans = 0
        self.last_at: float | None = None
        self.last_ok: bool | None = None
        self.last_error: str | None = None
        self.trace_ids: deque[str] = deque(maxlen=50)

    def export(self, spans: Any) -> Any:
        from opentelemetry.sdk.trace.export import SpanExportResult

        try:
            result = self.inner.export(spans)
        except Exception as exc:  # noqa: BLE001
            self.last_ok, self.last_error, self.last_at = False, f"{type(exc).__name__}: {exc}", time.time()
            return SpanExportResult.FAILURE
        ok = result == SpanExportResult.SUCCESS
        self.batches += 1
        self.spans += len(spans)
        self.last_at, self.last_ok = time.time(), ok
        self.last_error = None if ok else "export failed (see the harness log)"
        for span in spans:
            if span.parent is None:
                self.trace_ids.append(format(span.context.trace_id, "032x"))
        return result

    def shutdown(self) -> None:
        self.inner.shutdown()

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        return self.inner.force_flush(timeout_millis)


class Pipeline:
    def __init__(self, config: Config, secret: str, *, exporter: Any | None = None) -> None:
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        self.config = config
        self.endpoint = normalize_endpoint(config.endpoint, is_langfuse_key_pair(config.public_key, secret))
        self.trace_endpoint = signal_url(self.endpoint, "traces") if self.endpoint else ""
        self.langfuse = is_langfuse_endpoint(self.endpoint)
        self.headers = basic_auth(config.public_key, secret)
        if exporter is None:
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

            try:
                from opentelemetry.exporter.otlp.proto.http import Compression

                compression = Compression.Gzip if config.gzip else Compression.NoCompression
            except Exception:  # noqa: BLE001
                compression = None
            kwargs: dict[str, Any] = {
                "endpoint": self.trace_endpoint,
                "headers": self.headers,
                "timeout": max(1, config.export_timeout_ms // 1000),
            }
            if compression is not None:
                kwargs["compression"] = compression
            exporter = OTLPSpanExporter(**kwargs)
        self.exporter = CountingExporter(exporter)
        resource = Resource.create(
            {
                "service.name": config.service_name or os.environ.get("OTEL_SERVICE_NAME") or DEFAULT_SERVICE,
                "service.instance.id": f"{config.service_name or DEFAULT_SERVICE}@{os.uname().nodename if hasattr(os, 'uname') else 'host'}:{os.getpid()}",
                "telemetry.sdk.language": "python",
                "gen_ai.agent.system": AGENT_SYSTEM,
            }
        )
        self.provider = TracerProvider(resource=resource)
        self.provider.add_span_processor(
            BatchSpanProcessor(
                self.exporter,
                max_queue_size=max(config.max_queue_size, config.max_export_batch_size),
                max_export_batch_size=config.max_export_batch_size,
                schedule_delay_millis=config.trace_export_interval_ms,
                export_timeout_millis=config.export_timeout_ms,
            )
        )
        self.tracer = self.provider.get_tracer("pyharness-otel", "0.1.0")

    def flush(self, timeout_ms: int = 20000) -> bool:
        return self.provider.force_flush(timeout_ms)

    def shutdown(self) -> None:
        try:
            self.provider.shutdown()
        except Exception:  # noqa: BLE001
            pass


# ---------------------------------------------------------------------- span building
def _ns(seconds: float) -> int:
    return int(seconds * 1_000_000_000)


def _json(value: Any, limit: int) -> str:
    text = json.dumps(value, ensure_ascii=False, default=str)
    if len(text) > limit:
        return json.dumps({"truncated": True, "original_characters": len(text), "limit_characters": limit})
    return text


def _part_text(text: str) -> dict[str, Any]:
    return {"type": "text", "content": text}


def _parse_args(raw: Any) -> Any:
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except ValueError:
            return raw
    return raw


def build_turn_spans(
    tracer: Any,
    turn: dict[str, Any],
    *,
    session: dict[str, Any] | None,
    events: list[dict[str, Any]],
    capture: bool,
    limit: int,
    system_prompt: str | None,
    tool_defs: list[dict[str, Any]] | None,
    user_input: str | None,
) -> str | None:
    """Emit the trace of one turn from its record (``stats``, ``records``) and run events; returns the trace id."""
    from opentelemetry import trace
    from opentelemetry.trace import SpanKind, Status, StatusCode

    records = turn.get("records") or []
    stats = turn.get("stats") or {}
    started = float(turn.get("at") or time.time())
    end_rec = next((r for r in records if r.get("t") == "end"), None)
    ended = float(end_rec["at"]) if end_rec else started + (stats.get("duration_ms") or 0) / 1000
    session_id = turn.get("session_id") or ""
    seq = turn.get("seq") or 0
    outcome = turn.get("outcome") or "completed"
    preset = (session or {}).get("preset") or "standard"
    model = turn.get("model") or (session or {}).get("model") or ""
    provider, _, model_name = model.partition(":") if ":" in model else ("", "", model)
    common: dict[str, Any] = {
        "gen_ai.agent.system": AGENT_SYSTEM,
        "gen_ai.agent.name": preset,
        "gen_ai.session.id": session_id,
        "gen_ai.turn.id": f"{session_id}:{seq}",
        "pyharness.session.id": session_id,
        "pyharness.turn": seq,
        "pyharness.agent.preset": preset,
        "langfuse.session.id": session_id,
        "session.id": session_id,
    }
    if (session or {}).get("workspace"):
        common["pyharness.session.workspace"] = str(session["workspace"])
    end_reason = {"completed": "completed", "error": "error", "cancelled": "aborted", "interrupted": "interrupted"}.get(outcome, outcome)
    tokens_in = int(stats.get("input_tokens") or 0)
    cache_read = int(stats.get("cache_read_tokens") or 0)
    cache_write = int(stats.get("cache_write_tokens") or 0)
    tokens_out = int(stats.get("output_tokens") or 0)
    usage = {
        "gen_ai.usage.input_tokens": tokens_in,
        "gen_ai.usage.output_tokens": tokens_out,
        "gen_ai.usage.cache_read.input_tokens": cache_read,
        "gen_ai.usage.cache_creation.input_tokens": cache_write,
        "gen_ai.usage.total_tokens": tokens_in + tokens_out,
    }
    # Content from the run events.
    tool_calls = {e.get("id"): e for e in events if e.get("type") == "tool_call"}
    tool_results = {e.get("id"): e for e in events if e.get("type") == "tool_result"}
    final_text = "".join(str(e.get("text") or e.get("content") or "") for e in events if e.get("type") == "token")
    input_messages = [{"role": "user", "parts": [_part_text(user_input)]}] if user_input else []
    output_messages = [{"role": "assistant", "parts": [_part_text(final_text)], "finish_reason": "stop"}] if final_text else []

    def set_status(span: Any, ok: bool, code: str | None = None, message: str | None = None) -> None:
        if ok:
            span.set_status(Status(StatusCode.OK))
        else:
            span.set_status(Status(StatusCode.ERROR, message or code or "error"))
            span.set_attribute("error.type", code or "Error")

    entry = tracer.start_span(
        "enter_ai_application_system",
        kind=SpanKind.SERVER,
        start_time=_ns(started),
        attributes={**common, "gen_ai.operation.name": "enter", "gen_ai.span.kind": "ENTRY", "pyharness.turn.end_reason": end_reason},
    )
    trace_id = format(entry.get_span_context().trace_id, "032x")
    ttft_total = stats.get("ttft_ms")
    if ttft_total and stats.get("ttft_steps"):
        entry.set_attribute("gen_ai.response.time_to_first_token", int(ttft_total / stats["ttft_steps"] * 1_000_000))
    if capture:
        entry.set_attribute("gen_ai.input.messages", _json(input_messages, limit))
        entry.set_attribute("gen_ai.output.messages", _json(output_messages, limit))
    ctx_entry = trace.set_span_in_context(entry)
    agent = tracer.start_span(
        f"invoke_agent {preset}",
        kind=SpanKind.CLIENT,
        context=ctx_entry,
        start_time=_ns(started),
        attributes={
            **common,
            **usage,
            "gen_ai.operation.name": "invoke_agent",
            "gen_ai.span.kind": "AGENT",
            "gen_ai.agent.id": preset,
            "gen_ai.conversation.id": session_id,
            "gen_ai.provider.name": provider or AGENT_SYSTEM,
            "gen_ai.request.model": model_name,
            "pyharness.turn.end_reason": end_reason,
        },
    )
    if capture:
        agent.set_attribute("gen_ai.input.messages", _json(input_messages, limit))
        agent.set_attribute("gen_ai.output.messages", _json(output_messages, limit))
    ctx_agent = trace.set_span_in_context(agent)
    # Steps: each `step` record is one model call; the tool records that follow it belong to that step.
    step_no = 0
    finish_reasons: list[str] = []
    seen_tool_ids: set[str] = set()
    i = 0
    while i < len(records):
        rec = records[i]
        if rec.get("t") != "step":
            i += 1
            continue
        step_no += 1
        step_start = float(rec["at"])
        step_tools = []
        j = i + 1
        while j < len(records) and records[j].get("t") in ("tool", "compact"):
            if records[j].get("t") == "tool":
                step_tools.append(records[j])
            j += 1
        llm_end = step_start + (rec.get("dur_ms") or 0) / 1000
        step_end = max([llm_end] + [float(tr["at"]) + (tr.get("dur_ms") or 0) / 1000 for tr in step_tools])
        step_attrs = {**common, "gen_ai.step.id": f"{session_id}:{seq}:{step_no}", "pyharness.step": step_no}
        finish = "tool_calls" if rec.get("tool_calls") else "stop"
        step = tracer.start_span(
            "react step",
            kind=SpanKind.INTERNAL,
            context=ctx_agent,
            start_time=_ns(step_start),
            attributes={
                **step_attrs,
                "gen_ai.operation.name": "react",
                "gen_ai.span.kind": "STEP",
                "gen_ai.react.round": step_no,
                "gen_ai.react.finish_reason": finish,
            },
        )
        ctx_step = trace.set_span_in_context(step)
        llm_attrs: dict[str, Any] = {
            **step_attrs,
            "gen_ai.operation.name": "chat",
            "gen_ai.span.kind": "LLM",
            "gen_ai.request.model": model_name,
            "gen_ai.provider.name": provider or AGENT_SYSTEM,
            "gen_ai.conversation.id": session_id,
            "gen_ai.response.model": model_name,
            "gen_ai.response.finish_reasons": [finish],
            "pyharness.llm.attempt": 1,
        }
        if rec.get("output_tokens") is not None:
            inp = int(rec.get("input_tokens") or 0)
            llm_attrs.update(
                {
                    "gen_ai.usage.input_tokens": inp,
                    "gen_ai.usage.output_tokens": int(rec.get("output_tokens") or 0),
                    "gen_ai.usage.total_tokens": inp + int(rec.get("output_tokens") or 0),
                    "gen_ai.usage.cache_read.input_tokens": int(rec.get("cache_read_tokens") or 0),
                    "gen_ai.usage.cache_creation.input_tokens": int(rec.get("cache_write_tokens") or 0),
                    "gen_ai.usage.reasoning_tokens": int(rec.get("reasoning_tokens") or 0),
                }
            )
        if rec.get("ttft_ms") is not None:
            llm_attrs["gen_ai.response.time_to_first_token"] = int(rec["ttft_ms"] * 1_000_000)
        if capture:
            if system_prompt:
                llm_attrs["gen_ai.system_instructions"] = _json([_part_text(system_prompt)], limit)
            if tool_defs:
                llm_attrs["gen_ai.tool.definitions"] = _json(tool_defs, limit)
            llm_attrs["gen_ai.input.messages"] = _json(input_messages, limit)
            out_parts: list[dict[str, Any]] = []
            for tr in step_tools:
                call = tool_calls.get(tr.get("id")) or {}
                out_parts.append(
                    {"type": "tool_call", "id": tr.get("id"), "name": tr.get("name"), "arguments": _parse_args(call.get("args"))}
                )
            if not step_tools and final_text and step_no == stats.get("steps"):
                out_parts.append(_part_text(final_text))
            llm_attrs["gen_ai.output.messages"] = _json([{"role": "assistant", "parts": out_parts, "finish_reason": finish}], limit)
        llm = tracer.start_span(
            f"chat {model_name}".strip(), kind=SpanKind.CLIENT, context=ctx_step, start_time=_ns(step_start), attributes=llm_attrs
        )
        set_status(llm, True)
        llm.end(end_time=_ns(llm_end))
        finish_reasons.append(finish)
        for tr in step_tools:
            seen_tool_ids.add(str(tr.get("id")))
            t_start = float(tr["at"])
            t_end = t_start + (tr.get("dur_ms") or 0) / 1000
            attrs = {
                **step_attrs,
                "gen_ai.operation.name": "execute_tool",
                "gen_ai.span.kind": "TOOL",
                "gen_ai.tool.name": tr.get("name") or "",
                "gen_ai.tool.call.id": tr.get("id") or "",
                "gen_ai.tool.type": "function",
            }
            if capture:
                call = tool_calls.get(tr.get("id")) or {}
                result = tool_results.get(tr.get("id")) or {}
                attrs["gen_ai.tool.call.arguments"] = _json(_parse_args(call.get("args")), limit)
                attrs["gen_ai.tool.call.result"] = _json(result.get("content"), limit)
            tool_span = tracer.start_span(
                f"execute_tool {tr.get('name') or ''}".strip(),
                kind=SpanKind.INTERNAL,
                context=ctx_step,
                start_time=_ns(t_start),
                attributes=attrs,
            )
            status = tr.get("status") or "ok"
            set_status(
                tool_span,
                status not in ("error", "pending"),
                "ToolError" if status == "error" else "INTERRUPTED" if status == "pending" else None,
                f"tool {status}",
            )
            tool_span.end(end_time=_ns(t_end))
        set_status(step, True)
        step.end(end_time=_ns(step_end))
        i = j
    agent.set_attribute("gen_ai.response.finish_reasons", sorted(set(finish_reasons)) or ["unknown"])
    ok = outcome == "completed"
    code = {"error": "Error", "cancelled": "ABORTED", "interrupted": "INTERRUPTED"}.get(outcome)
    set_status(agent, ok or outcome == "interrupted", code, f"turn {outcome}")
    agent.end(end_time=_ns(ended))
    set_status(entry, ok or outcome == "interrupted", code, f"turn {outcome}")
    entry.end(end_time=_ns(ended))
    return trace_id


# ---------------------------------------------------------------------- service
class OtelService(Service):
    """Turn traces to an OTLP backend; the Observability settings page."""

    key = "otel"
    name = "pyharness-otel"
    inject = ["http", "webui"]
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
                            "parameters": t.tool_call_schema.model_json_schema() if hasattr(t, "tool_call_schema") else {},
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
        from pyharness import manage

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
        if fields.get("enabled", self.config.enabled) and not (fields.get("endpoint", self.config.endpoint) or "").strip():
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
        """Send test spans through a temporary pipeline built from ``data`` (or the saved settings); verify on Langfuse."""
        from opentelemetry.trace import SpanKind

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
                "pyharness-otel payload test", attributes={"pyharness.otel.test": True, "pyharness.otel.test.payload": payload}
            ) as s2:
                trace_ids.append(format(s2.get_span_context().trace_id, "032x"))
            await asyncio.to_thread(pipeline.flush)
            if pipeline.exporter.last_ok is False:
                raise HTTPException(
                    502, f"payload test (900 KB) failed: {pipeline.exporter.last_error}; the backend may cap the request size"
                )
            now = time.time()
            turn = {
                "session_id": "otel-test",
                "seq": 1,
                "outcome": "completed",
                "model": "deepseek:deepseek-chat",
                "at": now - 1.2,
                "stats": {"steps": 1, "input_tokens": 12, "output_tokens": 5, "ttft_ms": 120, "ttft_steps": 1, "duration_ms": 1200},
                "records": [
                    {"t": "user", "at": now - 1.2},
                    {"t": "step", "at": now - 1.1, "dur_ms": 900, "ttft_ms": 120, "tool_calls": 0, "input_tokens": 12, "output_tokens": 5},
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
                f"Tests passed: connectivity, 900 KB payload, GenAI turn ({pipeline.exporter.spans} spans{', gzip' if config.gzip else ''})."
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
        return {"ok": True, "message": " ".join(notes), "traceIds": trace_ids, "found": found, "traceEndpoint": pipeline.trace_endpoint}

    async def _verify_on_langfuse(self, pipeline: Pipeline, trace_ids: list[str], *, attempts: int, delay: float) -> dict[str, bool]:
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


__all__ = ["Config", "OtelService", "Pipeline", "build_turn_spans", "normalize_endpoint", "signal_url"]
