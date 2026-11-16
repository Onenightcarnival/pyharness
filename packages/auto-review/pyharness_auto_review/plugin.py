from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from pyharness import package_toml

from .middleware import ReviewMiddleware, reviewed

MODE: dict[str, str] = package_toml(__file__)["MODE"]

name = "pyharness-auto-review"
doc = "Auto review permission mode: a model reviews each gated tool call before it runs; a denied call asks the user."
inject = ["agentLoop", "llm"]


class Config(BaseModel):
    model: str | None = Field(None, description="Reviewer model spec; None: the model of the reviewed call.")
    timeout: float = Field(60.0, description="Seconds one review may take.")


def apply(ctx: Any, config: Config) -> None:
    def build(kwargs: dict[str, Any]) -> dict[str, Any]:
        gates = kwargs.get("interrupt_on") or {}
        if not gates:
            return kwargs
        kwargs["interrupt_on"] = reviewed(gates)
        kwargs["middleware"] = [*kwargs["middleware"], ReviewMiddleware(ctx, config, gates)]
        for spec in kwargs.get("subagents") or []:
            if "runnable" in spec or "graph_id" in spec or "interrupt_on" in spec:
                continue  # these keep their own approval gates
            spec["middleware"] = [*spec.get("middleware", []), ReviewMiddleware(ctx, config, gates, subagent=True)]
        return kwargs

    ctx.agentLoop.add_mode(MODE["id"], MODE["title"], MODE["description"], base="workspace-write", build=build)
