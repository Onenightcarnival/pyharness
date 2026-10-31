"""``ctx.agentLoop``: the default agent loop, built on deepagents.

Contract with ``ctx.agents``: ``build()`` returns a LangGraph graph with ``astream`` and
``aget_state``. Another loop replaces this entry through a patch.

``build(workspace, mode, preset)`` builds one graph; ``build()`` builds the default one on ``app/ready``.
Sessions choose a workspace (root directory), a permission mode and an agent preset; ``ctx.agents`` keeps
one graph per combination.

| permission mode     | effect                                                                  |
|---------------------|-------------------------------------------------------------------------|
| ``read-only``       | file writes denied, no ``execute`` tool, tools tagged ``shell`` left out; approvals as configured |
| ``workspace-write`` | writes inside the workspace; approvals as configured                    |
| ``full-access``     | writes inside the workspace; no approval gates                          |

| preset field      | effect                                                          |
|-------------------|-----------------------------------------------------------------|
| ``tools``         | registered tool names the preset keeps (``None``: all)          |
| ``exclude_tools`` | registered tool names the preset drops                          |
| ``skills``        | skills directories mounted for the preset (``add_skills``)      |
| prompt sections   | ``ctx.prompt.add(..., presets=[...])`` limits a section          |

``build()`` reads:

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

| hook       | route                                                                           |
|------------|---------------------------------------------------------------------------------|
| model call | model from ``configurable.model_spec`` or ``ctx.llm.default`` when it differs from the built one; then ``agent/model-request`` (waterfall) |

A default model that cannot be initialised at boot (missing package or credential) does not fail the boot outside
preflight: the graph is built with ``echo:echo`` and each request resolves the configured model, so the error
reaches the session and the settings page stays available.
| tool call  | ``ctx.tools.execute``                                                           |

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

MODES: dict[str, dict[str, str]] = {
    "read-only": {"title": "Read only", "description": "File tools read the workspace; writes and the shell are unavailable."},
    "workspace-write": {"title": "Workspace write", "description": "File tools write inside the workspace; gated tools ask for approval."},
    "full-access": {"title": "Full access", "description": "Workspace writes and the shell without approval prompts."},
}

DEFAULT_SYSTEM_PROMPT = (
    "Role: agent inside pyharness, a plugin-based agent harness.\nStyle: direct answers; tools where they help; failures reported plainly."
)


class PresetConfig(BaseModel):
    title: str
    description: str = ""
    tools: list[str] | None = Field(None, description="Registered tool names the preset keeps; None keeps all.")
    exclude_tools: list[str] = Field(default_factory=list, description="Registered tool names the preset drops.")
    order: int = 100


DEFAULT_PRESETS: dict[str, PresetConfig] = {
    "standard": PresetConfig(
        title="Standard",
        description="Everyday work in the workspace: files, shell, subagents. Plugin management stays out of the way.",
        exclude_tools=["plugin_manager", "harness_inspect"],
        order=1,
    ),
    "creator": PresetConfig(
        title="Creator",
        description="Standard plus harness inspection, plugin management and the plugin-authoring skills: extend the harness itself.",
        order=2,
    ),
}


class LoopConfig(BaseModel):
    model: str | None = Field(None, description="Model spec; None selects ctx.llm's default.")
    default_preset: str = Field("standard", description="Agent preset for new sessions.")
    default_mode: str = Field("workspace-write", description="Permission mode for new sessions: read-only, workspace-write, full-access.")
    presets: dict[str, PresetConfig] = Field(default_factory=lambda: dict(DEFAULT_PRESETS), description="Agent presets by id.")
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


def _configurable() -> dict[str, Any]:
    try:
        from langgraph.config import get_config

        return dict(get_config().get("configurable") or {})
    except Exception:
        return {}


def _thread_id() -> str | None:
    return _configurable().get("thread_id")


class HarnessMiddleware(AgentMiddleware):
    """LangChain middleware → harness events."""

    def __init__(self, ctx: Any, built_spec: str | None = None) -> None:
        super().__init__()
        self._ctx = ctx
        self._built_spec = built_spec

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
        configurable = _configurable()
        spec = configurable.get("model_spec") or self._ctx.llm.default
        if spec and spec != self._built_spec:
            request = request.override(model=self._ctx.llm.resolve(spec))
        call = ModelCall(session_id=configurable.get("thread_id"), request=request, meta={"model_spec": spec})
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
        self._skills: list[tuple[str, Path, str, tuple[str, ...] | None]] = []  # (label, directory, owner, presets)
        self._presets: dict[str, tuple[PresetConfig, str]] = {}  # plugin-added presets: id -> (config, owner)
        if self.config.default_mode not in MODES:
            raise ValueError(f"unknown default_mode {self.config.default_mode!r}; one of {', '.join(MODES)}")

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

    def add_skills(self, directory: str | Path, label: str | None = None, presets: list[str] | None = None) -> Any:
        """Mount ``directory`` (``<skill>/SKILL.md`` layout) read-only at ``/skills/<label>/`` for ``presets`` (``None``: all); returns the disposer."""
        path = Path(directory).expanduser().resolve()
        if not path.is_dir():
            raise ValueError(f"skills directory {path} does not exist")
        slug = re.sub(r"[^a-z0-9]+", "-", (label or path.name).lower()).strip("-") or "skills"
        if any(existing == slug for existing, _, _, _ in self._skills):
            raise ValueError(f"skills label {slug!r} is already mounted")
        item = (slug, path, self.caller.entry_id, tuple(presets) if presets else None)
        self._skills.append(item)
        return self.caller.on_dispose(lambda: self._skills.remove(item) if item in self._skills else None)

    def skills(self) -> list[dict[str, Any]]:
        """Mounted skills directories: ``label``, ``path``, ``mount``, ``owner``, ``presets``."""
        return [
            {"label": s, "path": str(p), "mount": f"{SKILLS_MOUNT}/{s}/", "owner": o, "presets": list(pr) if pr else None}
            for s, p, o, pr in self._skills
        ]

    # ------------------------------------------------------------------ presets and modes
    def add_preset(self, id: str, title: str, description: str = "", **fields: Any) -> Any:
        """Add an agent preset owned by the calling plugin; returns the disposer."""
        if id in self.config.presets or id in self._presets:
            raise ValueError(f"preset {id!r} already exists")
        item = (PresetConfig(title=title, description=description, **fields), self.caller.entry_id)
        self._presets[id] = item
        return self.caller.on_dispose(lambda: self._presets.pop(id, None))

    def preset(self, id: str | None) -> tuple[str, PresetConfig]:
        """``(id, config)`` of ``id`` or of the default preset; unknown ids raise ``ValueError``."""
        id = id or self.config.default_preset
        if id in self.config.presets:
            return id, self.config.presets[id]
        if id in self._presets:
            return id, self._presets[id][0]
        raise ValueError(f"unknown preset {id!r}; one of {', '.join(self.preset_ids())}")

    def preset_ids(self) -> list[str]:
        return [*self.config.presets, *(p for p in self._presets if p not in self.config.presets)]

    def presets(self) -> list[dict[str, Any]]:
        """Roster for selectors: ``id``, ``title``, ``description``, ``default``, ``owner``."""
        rows = []
        for id in self.preset_ids():
            cfg = self.config.presets.get(id) or self._presets[id][0]
            owner = self._presets[id][1] if id in self._presets else self.ctx.entry_id
            rows.append(
                {
                    "id": id,
                    "title": cfg.title,
                    "description": cfg.description,
                    "order": cfg.order,
                    "default": id == self.config.default_preset,
                    "owner": owner,
                }
            )
        return sorted(rows, key=lambda r: (r["order"], r["id"]))

    def modes(self) -> list[dict[str, Any]]:
        return [{"id": id, **info, "default": id == self.config.default_mode} for id, info in MODES.items()]

    def mode(self, id: str | None) -> str:
        id = id or self.config.default_mode
        if id not in MODES:
            raise ValueError(f"unknown permission mode {id!r}; one of {', '.join(MODES)}")
        return id

    def set_defaults(self, preset: str | None = None, mode: str | None = None) -> dict[str, str]:
        """Change the defaults for new sessions (live); the settings API persists them."""
        if preset is not None:
            self.config.default_preset = self.preset(preset)[0]
        if mode is not None:
            self.config.default_mode = self.mode(mode)
        return {"default_preset": self.config.default_preset, "default_mode": self.config.default_mode}

    def _backend_and_skills(self, workspace: str | None, mode: str, preset: str) -> tuple[Any, list[str], list[Any]]:
        """Backend for the workspace and mode with the preset's skills routes, the skill sources, and the write-deny rules."""
        from deepagents import FilesystemPermission

        workspaces = self.ctx.get("workspace", None)
        if workspaces is not None and hasattr(workspaces, "backend_for"):
            backend = workspaces.backend_for(workspace, shell=mode != "read-only")
        else:
            backend = self.ctx.get("backend", None)
        sources = list(self.config.skills or [])
        rules: list[Any] = []
        if mode == "read-only":
            rules.append(FilesystemPermission(operations=["write"], paths=["/", "/**"], mode="deny"))
        mounts = [(s, p) for s, p, _, presets in self._skills if presets is None or preset in presets]
        if not mounts:
            return backend, sources, rules
        from deepagents.backends import CompositeBackend, FilesystemBackend, StateBackend

        routes: dict[str, Any] = {}
        for slug, path in mounts:
            mount = f"{SKILLS_MOUNT}/{slug}/"
            routes[mount] = FilesystemBackend(root_dir=path, virtual_mode=True)
            sources.append(mount)
        composite = CompositeBackend(default=backend if backend is not None else StateBackend(), routes=routes)
        rules.append(FilesystemPermission(operations=["write"], paths=[SKILLS_MOUNT, f"{SKILLS_MOUNT}/**"], mode="deny"))
        return composite, sources, rules

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

    def _built_model(self) -> tuple[str | None, Any]:
        """Model the graph is built with. An unusable default falls back to ``echo:echo`` so the harness boots;
        requests then resolve the configured model and report its error in the session."""
        from pyharness_llm import LLMConfigError

        spec = self.config.model or self.ctx.llm.default
        try:
            return spec, self.ctx.llm.resolve(spec)
        except LLMConfigError as exc:
            if self.ctx.lifecycle.preflight or "echo" not in self.ctx.llm.providers():
                raise
            self.ctx.logger.warning(
                "default model %s unusable at boot (%s); built with echo:echo, requests resolve the configured model", spec, exc
            )
            return "echo:echo", self.ctx.llm.resolve("echo:echo")

    async def build(self, workspace: str | None = None, mode: str | None = None, preset: str | None = None) -> Any:
        """Graph for a workspace root (``None``: the default), a permission mode and an agent preset."""
        from deepagents import create_deep_agent
        from deepagents.middleware.subagents import GENERAL_PURPOSE_SUBAGENT

        ctx = self.ctx
        mode = self.mode(mode)
        preset_id, preset_cfg = self.preset(preset)
        keep = set(preset_cfg.tools) if preset_cfg.tools is not None else None
        drop = set(preset_cfg.exclude_tools)
        tools = [t for t in ctx.tools.list() if (keep is None or t.name in keep) and t.name not in drop]
        if mode == "read-only":  # tools tagged `shell` (the persistent bash, background commands) stay out
            shell_tools = {r.tool.name for r in ctx.tools.records() if "shell" in r.tags}
            tools = [t for t in tools if t.name not in shell_tools]
        registry = {t.name: t for t in tools}
        subagents = [self._resolve_subagent(s, registry) for s in self.config.subagents]
        subagents += [self._resolve_subagent(s, registry) for s, _ in self._subagents]
        # Every declarative subagent, the general-purpose one included, carries HarnessMiddleware.
        if not any(s.get("name") == GENERAL_PURPOSE_SUBAGENT["name"] for s in subagents):
            subagents.insert(0, dict(GENERAL_PURPOSE_SUBAGENT))
        built_spec, built_model = self._built_model()
        for spec in subagents:
            if "runnable" in spec or "graph_id" in spec:
                continue  # compiled and remote subagents keep their own middleware
            spec["middleware"] = [HarnessMiddleware(ctx, built_spec), *spec.get("middleware", [])]
        workspaces = ctx.get("workspace", None)
        ws = workspaces.open(workspace) if workspaces is not None and hasattr(workspaces, "open") else workspaces
        permissions = ws.permissions() if ws is not None and hasattr(ws, "permissions") else []
        backend, skills, rules = self._backend_and_skills(workspace, mode, preset_id)
        permissions = [*permissions, *rules]
        interrupt_on = {} if mode == "full-access" else {**ctx.tools.interrupt_on(), **self.config.interrupt_on}
        policy = (
            f"## Session policy\nPermission mode: {MODES[mode]['title']}. {MODES[mode]['description']}\n"
            f"Agent preset: {preset_cfg.title}. Workspace root: {ws.root if ws is not None and hasattr(ws, 'root') else '(none)'}; "
            "the file tools address it as `/` (paths inside the workspace are relative to that root)."
        )
        kwargs: dict[str, Any] = {
            "model": built_model,
            "tools": tools,
            "system_prompt": ctx.prompt.render(preset_id) + "\n\n" + policy,
            "middleware": [HarnessMiddleware(ctx, built_spec), *(m for m, _ in self._middleware)],
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


__all__ = ["DEFAULT_PRESETS", "MODES", "SKILLS_MOUNT", "DeepAgentsLoop", "HarnessMiddleware", "LoopConfig", "ModelCall", "PresetConfig"]
