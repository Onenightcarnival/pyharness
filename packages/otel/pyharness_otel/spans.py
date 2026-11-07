"""The GenAI span tree of one turn: ENTRY → AGENT → STEP → LLM / TOOL spans built from the turn record."""

from __future__ import annotations

import json
import time
from typing import Any

AGENT_SYSTEM = "pyharness"
FINISH = {"tool-calls": "tool_calls", "max-tokens": "length", "aborted": "cancelled", "stop": "stop", "error": "error"}


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
    end_reason = {"completed": "completed", "error": "error", "cancelled": "aborted", "interrupted": "interrupted"}.get(
        outcome, outcome
    )
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
    output_messages = (
        [{"role": "assistant", "parts": [_part_text(final_text)], "finish_reason": "stop"}] if final_text else []
    )

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
        attributes={
            **common,
            "gen_ai.operation.name": "enter",
            "gen_ai.span.kind": "ENTRY",
            "pyharness.turn.end_reason": end_reason,
        },
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
                    {
                        "type": "tool_call",
                        "id": tr.get("id"),
                        "name": tr.get("name"),
                        "arguments": _parse_args(call.get("args")),
                    }
                )
            if not step_tools and final_text and step_no == stats.get("steps"):
                out_parts.append(_part_text(final_text))
            llm_attrs["gen_ai.output.messages"] = _json(
                [{"role": "assistant", "parts": out_parts, "finish_reason": finish}], limit
            )
        llm = tracer.start_span(
            f"chat {model_name}".strip(),
            kind=SpanKind.CLIENT,
            context=ctx_step,
            start_time=_ns(step_start),
            attributes=llm_attrs,
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
