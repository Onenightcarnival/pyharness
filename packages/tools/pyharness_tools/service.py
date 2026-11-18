from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from textwrap import dedent
from typing import Any

from langchain_core.tools import BaseTool, tool as as_tool

from pyharness import Service


@dataclass
class ToolCall:
    """One tool call as ``tools/*`` listeners see it."""

    name: str
    args: dict[str, Any]
    id: str | None
    session_id: str | None
    request: Any = None  # langchain ToolCallRequest
    owner: str | None = None  # registering entry; None for loop built-ins
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass
class ToolRecord:
    tool: BaseTool
    owner: str
    approval: bool | dict[str, Any] = False
    tags: tuple[str, ...] = ()

    def describe(self) -> dict[str, Any]:
        return {
            "name": self.tool.name,
            "owner": self.owner,
            "description": ((self.tool.description or "").strip().splitlines() or [""])[0],
            "approval": bool(self.approval),
            "tags": list(self.tags),
        }


class ToolError(RuntimeError):
    pass


class ToolsService(Service):
    """Tool registry and the ``tools/execute`` → ``tools/result`` pipeline."""

    key = "tools"
    name = "pyxis-harness-tools"

    def __init__(self, ctx: Any, config: Any) -> None:
        super().__init__(ctx, config)
        self._records: dict[str, ToolRecord] = {}
        # tool name -> [(config, owner)]
        self._approvals: dict[str, list[tuple[bool | dict[str, Any], str]]] = {}

    async def start(self) -> None:
        self.ctx.define_event(
            "tools/execute",
            "waterfall",
            dedent(
                """
                listener(call: ToolCall, next) -> ToolMessage | Command. `await next()` runs the tool;
                a returned ToolMessage without next() replaces the tool.
                """
            ).strip(),
        )
        self.ctx.define_event("tools/result", "parallel", "listener(call: ToolCall, result) after each tool call.")

    # ------------------------------------------------------------------ registry
    def register(
        self,
        tool: BaseTool | Callable[..., Any],
        *,
        approval: bool | dict[str, Any] = False,
        tags: tuple[str, ...] | list[str] = (),
    ) -> Callable[[], Any]:
        """
        Register a tool owned by the calling plugin; returns the disposer.

        | ``approval`` | effect                                                                            |
        |--------------|-----------------------------------------------------------------------------------|
        | ``False``    | no gate                                                                           |
        | ``True``     | every call waits for a human decision                                             |
        | ``dict``     | LangChain ``InterruptOnConfig``: ``allowed_decisions``, ``description``, ``when`` |
        """
        if not isinstance(tool, BaseTool):
            tool = as_tool(tool)
        name = tool.name
        if name in self._records:
            raise ToolError(f"tool {name!r} is already registered by {self._records[name].owner!r}")
        owner = self.caller.entry_id
        self._records[name] = ToolRecord(tool=tool, owner=owner, approval=approval, tags=tuple(tags))

        def dispose() -> None:
            record = self._records.get(name)
            if record is not None and record.tool is tool:
                del self._records[name]

        return self.caller.on_dispose(dispose)

    def require_approval(self, tool_name: str, config: bool | dict[str, Any] = True) -> Callable[[], Any]:
        """
        Gate a tool the calling plugin does not own; returns the disposer.

        Gates accumulate per owner; a disposer removes only its owner's gate.
        """
        if not config:
            return lambda: None
        item = (config, self.caller.entry_id)
        self._approvals.setdefault(tool_name, []).append(item)

        def dispose() -> None:
            items = self._approvals.get(tool_name, [])
            if item in items:
                items.remove(item)
            if not items:
                self._approvals.pop(tool_name, None)

        return self.caller.on_dispose(dispose)

    def list(self) -> list[BaseTool]:
        return [record.tool for record in self._records.values()]

    def records(self) -> list[ToolRecord]:
        return list(self._records.values())

    def owner_of(self, name: str) -> str | None:
        record = self._records.get(name)
        return record.owner if record else None

    def interrupt_on(self) -> dict[str, Any]:
        """``tool name -> gate`` for the agent loop; one gate per tool, the strictest (:func:`_strictest`)."""
        gates: dict[str, list[bool | dict[str, Any]]] = {
            name: [c for c, _ in items] for name, items in self._approvals.items()
        }
        for name, record in self._records.items():
            if record.approval:
                gates.setdefault(name, []).append(record.approval)
        return {name: _strictest(configs) for name, configs in gates.items() if configs}

    # ------------------------------------------------------------------ pipeline
    async def execute(self, call: ToolCall, handler: Callable[[Any], Awaitable[Any]]) -> Any:
        """Dispatch ``tools/execute`` around ``handler``, then ``tools/result``; returns the result."""
        if call.owner is None:
            call.owner = self.owner_of(call.name)
        result = await self.ctx.waterfall("tools/execute", call, final=lambda c: handler(c.request))
        await self.ctx.parallel("tools/result", call, result)
        return result


def _strictest(configs: list[bool | dict[str, Any]]) -> bool | dict[str, Any]:
    """Strictest gate: unconditional over ``when``-conditional, then fewest allowed decisions."""
    unconditional = [c for c in configs if not (isinstance(c, dict) and c.get("when"))]
    pool = unconditional or configs
    dicts = [c for c in pool if isinstance(c, dict)]
    if not dicts:
        return True
    return min(dicts, key=lambda c: len(c.get("allowed_decisions") or ("approve", "edit", "reject", "respond")))
