from __future__ import annotations

import inspect as _inspect
import json
from textwrap import dedent
from typing import Any, Literal

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from pyharness import Service, package_prompts, unwrap

PROMPTS = package_prompts(__file__)

name = "pyharness-inspect"
doc = "``harness_inspect`` tool: read-only view of the running harness."
inject = ["tools"]

Topic = Literal["overview", "services", "events", "plugins", "config", "tools", "routes", "prompt", "ui"]


class Config(BaseModel):
    max_chars: int = Field(12000, description="Maximum tool output in characters.")


def _signature(fn: Any) -> str:
    try:
        return str(_inspect.signature(fn))
    except (TypeError, ValueError):
        return "(...)"


def _methods(obj: Any, detail: bool) -> list[dict[str, Any]]:
    cls = type(obj)
    out = []
    for attr in sorted(dir(cls)):
        if attr.startswith("_") or attr in {
            "ctx",
            "config",
            "caller",
            "start",
            "stop",
            "key",
            "name",
            "inject",
            "Config",
        }:
            continue
        member = getattr(cls, attr, None)
        if member is None or not callable(member) or _inspect.isclass(member):
            continue
        if isinstance(_inspect.getattr_static(cls, attr), (staticmethod,)) and not detail:
            continue
        doc = _inspect.getdoc(member) or ""
        item = {"name": attr, "signature": _signature(member), "async": _inspect.iscoroutinefunction(member)}
        item["doc"] = doc if detail else (doc.splitlines()[0] if doc else "")
        out.append(item)
    return out


REDACTED = "<from environment: redacted>"
_SECRET_WORDS = ("key", "secret", "token", "password", "passwd", "dsn", "credential")


def _redact(effective: Any, raw: Any) -> Any:
    """Redact values from ``${env:...}`` and non-empty fields whose name contains a secret word."""
    if isinstance(effective, dict):
        out = {}
        for key, value in effective.items():
            raw_value = raw.get(key) if isinstance(raw, dict) else None
            if isinstance(raw_value, str) and "${env:" in raw_value:
                out[key] = REDACTED
            elif any(word in str(key).lower() for word in _SECRET_WORDS) and value not in (None, "", [], {}):
                out[key] = "<redacted>"
            else:
                out[key] = _redact(value, raw_value)
        return out
    if isinstance(effective, list):
        raws = raw if isinstance(raw, list) else []
        return [_redact(v, raws[i] if i < len(raws) else None) for i, v in enumerate(effective)]
    return effective


class Inspector:
    def __init__(self, ctx: Any) -> None:
        self.ctx = ctx

    def services(self, name: str | None) -> Any:
        visible = self.ctx.scope.all_services()
        if name:
            if name not in visible:
                return {"error": f"no service {name!r}", "available": sorted(visible)}
            value, owner, scope = visible[name]
            value = unwrap(value)
            return {
                "key": name,
                "owner": owner,
                "scope": scope,
                "type": f"{type(value).__module__}.{type(value).__qualname__}",
                "doc": _inspect.getdoc(type(value)) or "",
                "methods": _methods(value, detail=True) if isinstance(value, Service) else [],
            }
        rows = []
        for key, (raw, owner, _scope) in sorted(visible.items()):
            value = unwrap(raw)
            doc = _inspect.getdoc(type(value)) or ""
            rows.append(
                {
                    "key": key,
                    "owner": owner,
                    "type": type(value).__qualname__,
                    "doc": doc.splitlines()[0] if doc else "",
                }
            )
        return rows

    def events(self, name: str | None) -> Any:
        bus = self.ctx.events
        rows = []
        for decl in bus.declarations():
            if name and decl.name != name:
                continue
            rows.append(
                {
                    "name": decl.name,
                    "mode": decl.mode,
                    "doc": decl.doc,
                    "declared_by": decl.owners,
                    "listeners": [listener.owner for listener in bus.listeners(decl.name)],
                }
            )
        if name and not rows:
            return {"error": f"no event {name!r}", "available": [d.name for d in bus.declarations()]}
        return rows

    def plugins(self, name: str | None) -> Any:
        rows = self.ctx.loader.snapshot()
        if name:
            match = [r for r in rows if r["id"] == name or r.get("name") == name]
            return match or {"error": f"no entry {name!r}"}
        return [
            {k: r.get(k) for k in ("id", "name", "state", "kind", "provides", "inject", "missing", "error") if r.get(k)}
            for r in rows
        ]

    def config(self, name: str | None) -> Any:
        loader = self.ctx.loader
        if not name:
            return [
                {
                    "id": rt.entry.id,
                    "name": rt.entry.name,
                    "state": rt.state.value,
                    "has_schema": bool(rt.spec and rt.spec.config_model),
                }
                for rt in loader.runtimes
            ]
        rt = loader.get(name)
        if rt is None:
            return {"error": f"no entry {name!r}; name: entry id"}
        data: dict[str, Any] = {
            "id": rt.entry.id,
            "name": rt.entry.name,
            "state": rt.state.value,
            "raw_config": rt.entry.config or {},
        }
        if rt.spec is not None:
            data["schema"] = rt.spec.config_schema()
            data["package_dir"] = rt.spec.package_dir
            data["docs"] = rt.spec.docs
            data["doc"] = rt.spec.doc
        if rt.config is not None and hasattr(rt.config, "model_dump"):
            data["effective_config"] = _redact(rt.config.model_dump(mode="json"), rt.entry.config or {})
        return data

    def tools(self, name: str | None) -> Any:
        records = self.ctx.tools.records()
        if name:
            for record in records:
                if record.tool.name == name:
                    schema = record.tool.tool_call_schema
                    return {
                        **record.describe(),
                        "description": record.tool.description,
                        "args_schema": schema.model_json_schema() if hasattr(schema, "model_json_schema") else schema,
                    }
            return {"error": f"no registered tool {name!r}; agent-loop built-ins (read_file …) unlisted"}
        return {
            "registered": [r.describe() for r in records],
            "approval_gates": sorted(self.ctx.tools.interrupt_on()),
        }

    def routes(self, name: str | None) -> Any:
        http = self.ctx.get("http", None)
        if http is None:
            return {"error": "no http service is active"}
        return {"contributions": http.contributions(), "routes": http.routes()}

    def prompt(self, name: str | None) -> Any:
        prompt = self.ctx.get("prompt", None)
        if prompt is None:
            return {"error": "no prompt service is active"}
        return prompt.sections()

    def ui(self, name: str | None) -> Any:
        webui = self.ctx.get("webui", None)
        if webui is None:
            return {"error": "no webui service is active"}
        slots = webui.slots()
        if name:
            match = [s for s in slots if s["name"] == name]
            return match or {"error": f"no slot {name!r}", "available": [s["name"] for s in slots]}
        return {
            "slots": slots,
            "clients": webui.clients(),
            "contract": dedent(
                """
                ctx.webui.register_client(path, calls={...});
                the page: window.__PyhModules__.load({id, factory(require) { return { apply(ctx) {...} } }})
                """
            ).strip(),
        }

    def overview(self, name: str | None) -> Any:
        lifecycle = self.ctx.lifecycle
        profile = self.ctx.get("profile", None)
        return {
            "generation": lifecycle.generation,
            "supervised": lifecycle.supervised,
            "profile": profile.describe() if profile is not None else None,
            "entries": self.ctx.loader.summary(),
            "services": sorted(self.ctx.scope.all_services()),
            "events": [f"{d.name} ({d.mode})" for d in self.ctx.events.declarations()],
            "topics": list(Topic.__args__),  # type: ignore[attr-defined]
        }


def apply(ctx: Any, config: Config) -> None:
    inspector = Inspector(ctx)

    def harness_inspect(topic: Topic = "overview", name: str | None = None) -> str:
        result = getattr(inspector, topic)(name)
        text = json.dumps(result, ensure_ascii=False, indent=1, default=str)
        if len(text) > config.max_chars:
            text = text[: config.max_chars] + f"\n... truncated ({len(text)} chars); `name` narrows the result."
        return text

    ctx.tools.register(
        StructuredTool.from_function(
            harness_inspect, name="harness_inspect", description=PROMPTS["tools"]["harness_inspect"]
        )
    )


__all__ = ["REDACTED", "Config", "Inspector", "Topic", "apply", "doc", "inject", "name"]
