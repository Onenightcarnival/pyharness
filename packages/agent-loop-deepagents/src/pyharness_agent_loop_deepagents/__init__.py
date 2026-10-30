"""``ctx.agentLoop``: the default agent loop, built on deepagents.

Contract with ``ctx.agents``: ``build()`` returns a LangGraph graph with ``astream`` and
``aget_state``. Another loop replaces this entry through a patch.

``build()`` runs on ``app/ready`` and reads:

| input         | source                                                          |
|---------------|-----------------------------------------------------------------|
| model         | ``ctx.llm``                                                     |
| tools         | ``ctx.tools``                                                   |
| system prompt | ``ctx.prompt``                                                  |
| persistence   | ``ctx.checkpointer``; ``ctx.store`` when present                |
| files, shell  | ``ctx.backend`` and ``ctx.workspace`` permissions, when present |
| approvals     | ``ctx.tools.interrupt_on()`` and ``config.interrupt_on``        |
| subagents     | ``config.subagents`` and :meth:`DeepAgentsLoop.add_subagent`    |
| skills        | ``config.skills`` and :meth:`DeepAgentsLoop.add_skills`         |

:class:`HarnessMiddleware` runs in the main agent and in every declarative subagent:

| hook       | route                               |
|------------|-------------------------------------|
| model call | ``agent/model-request`` (waterfall) |
| tool call  | ``ctx.tools.execute``               |

``agent-loop/build`` (waterfall) receives the ``create_deep_agent`` keyword arguments.

Skills directories added by plugins are mounted read-only for the model at ``/skills/<label>/``
(``CompositeBackend`` route over ``ctx.backend``); deepagents lists them in the system prompt and
the model reads a skill with ``read_file``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from langchain.agents.middleware import AgentMiddleware
from pydantic import BaseModel, Field
from pyharness_tools import ToolCall

from pyharness import Service

SKILLS_MOUNT = "/skills"

DEFAULT_SYSTEM_PROMPT = (
    "Role: agent inside pyharness, a plugin-based agent harness.\nStyle: direct answers; tools where they help; failures reported plainly."
)


class LoopConfig(BaseModel):
    model: str | None = Field(None, description="Model spec; None selects ctx.llm's default.")
    system_prompt: str = Field(DEFAULT_SYSTEM_PROMPT, description="Identity section of the system prompt (order 0).")
    interrupt_on: dict[str, Any] = Field(default_factory=dict, description="Additional approval gates by tool name.")
    subagents: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Declarative deepagents SubAgent specs; `tools` entries are registered tool names or tools.",
    )
    skills: list[str] | None = Field(None, description="Skill source paths in the backend (workspace paths such as /skills/mine/).")
    memory: list[str] | None = Field(None, description="AGENTS.md-style memory files, relative to the backend root.")
    recursion_limit: int = 200


@dataclass
class ModelCall:
    """One model call as ``agent/model-request`` listeners see it."""

    session_id: str | None
    request: Any  # langchain ModelRequest; replaceable: call.request = call.request.override(...)
    meta: dict[str, Any] = field(default_factory=dict)


def _thread_id() -> str | None:
    try:
        from langgraph.config import get_config

        return (get_config().get("configurable") or {}).get("thread_id")
    except Exception:
        return None


class HarnessMiddleware(AgentMiddleware):
    """LangChain middleware → harness events."""

    def __init__(self, ctx: Any) -> None:
        super().__init__()
        self._ctx = ctx

    @property
    def name(self) -> str:  # type: ignore[override]
        return "PyHarnessMiddleware"

    async def awrap_tool_call(self, request: Any, handler: Any) -> Any:
        tool_call = request.tool_call
        call = ToolCall(
            name=tool_call["name"],
            args=dict(tool_call.get("args") or {}),
            id=tool_call.get("id"),
            session_id=_thread_id(),
            request=request,
        )
        return await self._ctx.tools.execute(call, handler)

    async def awrap_model_call(self, request: Any, handler: Any) -> Any:
        call = ModelCall(session_id=_thread_id(), request=request)
        return await self._ctx.waterfall("agent/model-request", call, final=lambda c: handler(c.request))


class DeepAgentsLoop(Service):
    """deepagents graph built from the services of other plugins."""

    key = "agentLoop"
    name = "pyharness-agent-loop-deepagents"
    inject = ["llm", "tools", "prompt", "checkpointer"]
    Config = LoopConfig

    def __init__(self, ctx: Any, config: LoopConfig) -> None:
        super().__init__(ctx, config)
        self._subagents: list[tuple[dict[str, Any], str]] = []
        self._middleware: list[tuple[AgentMiddleware, str]] = []
        self._skills: list[tuple[str, Path, str]] = []  # (label, directory, owner)

    async def start(self) -> None:
        self.ctx.define_event(
            "agent/model-request",
            "waterfall",
            "listener(call: ModelCall, next) around each model call; `await next()` returns the ModelResponse.",
        )
        self.ctx.define_event(
            "agent-loop/build",
            "waterfall",
            "listener(kwargs: dict, next) before create_deep_agent(**kwargs); listeners edit kwargs and return `await next()`.",
        )
        self.ctx.prompt.add("identity", self.config.system_prompt, order=0)

    @property
    def recursion_limit(self) -> int:
        return self.config.recursion_limit

    # ------------------------------------------------------------------ extension points
    def add_subagent(self, spec: dict[str, Any]) -> Any:
        """Add a declarative subagent spec owned by the calling plugin; returns the disposer."""
        item = (dict(spec), self.caller.entry_id)
        self._subagents.append(item)
        return self.caller.on_dispose(lambda: self._subagents.remove(item) if item in self._subagents else None)

    def add_middleware(self, middleware: AgentMiddleware) -> Any:
        """Add a LangChain ``AgentMiddleware`` after :class:`HarnessMiddleware`; returns the disposer."""
        item = (middleware, self.caller.entry_id)
        self._middleware.append(item)
        return self.caller.on_dispose(lambda: self._middleware.remove(item) if item in self._middleware else None)

    def subagents(self) -> list[dict[str, Any]]:
        return [{"name": s.get("name"), "owner": owner} for s, owner in self._subagents]

    def add_skills(self, directory: str | Path, label: str | None = None) -> Any:
        """Mount ``directory`` (``<skill>/SKILL.md`` layout) read-only at ``/skills/<label>/``; returns the disposer."""
        path = Path(directory).expanduser().resolve()
        if not path.is_dir():
            raise ValueError(f"skills directory {path} does not exist")
        slug = re.sub(r"[^a-z0-9]+", "-", (label or path.name).lower()).strip("-") or "skills"
        if any(existing == slug for existing, _, _ in self._skills):
            raise ValueError(f"skills label {slug!r} is already mounted")
        item = (slug, path, self.caller.entry_id)
        self._skills.append(item)
        return self.caller.on_dispose(lambda: self._skills.remove(item) if item in self._skills else None)

    def skills(self) -> list[dict[str, Any]]:
        """Mounted skills directories: ``label``, ``path``, ``mount``, ``owner``."""
        return [{"label": s, "path": str(p), "mount": f"{SKILLS_MOUNT}/{s}/", "owner": o} for s, p, o in self._skills]

    def _backend_and_skills(self) -> tuple[Any, list[str], list[Any]]:
        """``ctx.backend`` with skills routes, the skill source paths, and the write-deny rule for the mounts."""
        backend = self.ctx.get("backend", None)
        sources = list(self.config.skills or [])
        if not self._skills:
            return backend, sources, []
        from deepagents import FilesystemPermission
        from deepagents.backends import CompositeBackend, FilesystemBackend, StateBackend

        routes: dict[str, Any] = {}
        for slug, path, _ in self._skills:
            mount = f"{SKILLS_MOUNT}/{slug}/"
            routes[mount] = FilesystemBackend(root_dir=path, virtual_mode=True)
            sources.append(mount)
        composite = CompositeBackend(default=backend if backend is not None else StateBackend(), routes=routes)
        deny = FilesystemPermission(operations=["write"], paths=[SKILLS_MOUNT, f"{SKILLS_MOUNT}/**"], mode="deny")
        return composite, sources, [deny]

    # ------------------------------------------------------------------ build
    def _resolve_subagent(self, spec: dict[str, Any], registry: dict[str, Any]) -> dict[str, Any]:
        spec = dict(spec)
        tools = spec.get("tools")
        if tools is not None:
            resolved = []
            for item in tools:
                if isinstance(item, str):
                    if item not in registry:
                        raise ValueError(f"subagent {spec.get('name')!r} references unknown tool {item!r}")
                    resolved.append(registry[item])
                else:
                    resolved.append(item)
            spec["tools"] = resolved
        if isinstance(spec.get("model"), str):
            spec["model"] = self.ctx.llm.resolve(spec["model"])
        return spec

    async def build(self) -> Any:
        from deepagents import create_deep_agent
        from deepagents.middleware.subagents import GENERAL_PURPOSE_SUBAGENT

        ctx = self.ctx
        tools = ctx.tools.list()
        registry = {t.name: t for t in tools}
        subagents = [self._resolve_subagent(s, registry) for s in self.config.subagents]
        subagents += [self._resolve_subagent(s, registry) for s, _ in self._subagents]
        # Every declarative subagent, the general-purpose one included, carries HarnessMiddleware.
        if not any(s.get("name") == GENERAL_PURPOSE_SUBAGENT["name"] for s in subagents):
            subagents.insert(0, dict(GENERAL_PURPOSE_SUBAGENT))
        for spec in subagents:
            if "runnable" in spec or "graph_id" in spec:
                continue  # compiled and remote subagents keep their own middleware
            spec["middleware"] = [HarnessMiddleware(ctx), *spec.get("middleware", [])]
        workspace = ctx.get("workspace", None)
        permissions = workspace.permissions() if workspace is not None and hasattr(workspace, "permissions") else []
        backend, skills, skill_rules = self._backend_and_skills()
        permissions = [*permissions, *skill_rules]
        interrupt_on = {**ctx.tools.interrupt_on(), **self.config.interrupt_on}
        kwargs: dict[str, Any] = {
            "model": ctx.llm.resolve(self.config.model),
            "tools": tools,
            "system_prompt": ctx.prompt.render(),
            "middleware": [HarnessMiddleware(ctx), *(m for m, _ in self._middleware)],
            "checkpointer": ctx.get("checkpointer"),
            "store": ctx.get("store", None),
            "backend": backend,
            "interrupt_on": interrupt_on or None,
            "subagents": subagents or None,
            "permissions": permissions or None,
            "skills": skills or None,
            "memory": self.config.memory,
            "name": "pyharness",
        }
        kwargs = await ctx.waterfall("agent-loop/build", kwargs, final=lambda kw: kw)
        return create_deep_agent(**{k: v for k, v in kwargs.items() if v is not None})


__all__ = ["SKILLS_MOUNT", "DeepAgentsLoop", "HarnessMiddleware", "LoopConfig", "ModelCall"]
