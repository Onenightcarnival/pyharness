"""``DeepAgentsLoop``: the ``agentLoop`` service; extension points, presets and modes, ``build()``.

| member               | contract                                                                        |
|----------------------|---------------------------------------------------------------------------------|
| ``build()``          | :func:`pyharness_agent_loop_deepagents.graph.build`                             |
| ``add_subagent()``   | declarative subagent spec owned by the calling plugin; returns the disposer     |
| ``add_middleware()`` | LangChain ``AgentMiddleware`` after :class:`HarnessMiddleware`; returns the disposer |
| ``add_skills()``     | skills directory mounted read-only at ``/skills/<label>/``; returns the disposer |
| ``add_preset()``     | agent preset owned by the calling plugin; returns the disposer                  |
| ``preset()``         | ``(id, config)`` of a preset id or of the default; unknown ids raise ``ValueError`` |
| ``mode()``           | a permission mode id or the default; unknown ids raise ``ValueError``           |
| ``set_defaults()``   | the defaults for new sessions (live); the settings API persists them           |
| ``presets()``        | roster for selectors: ``id``, ``title``, ``description``, ``order``, ``default``, ``owner`` |
| ``modes()``          | roster for selectors: ``id``, ``title``, ``description``, ``default``           |
| ``skills()``         | mounted skills directories: ``label``, ``path``, ``mount``, ``owner``, ``presets`` |
| ``subagents()``      | ``name`` and ``owner`` of every added subagent                                  |
| ``recursion_limit``  | ``config.recursion_limit``                                                      |

Events defined at start: ``agent/model-request`` (waterfall) and ``agent-loop/build`` (waterfall). The identity
section of the system prompt (order 0) is ``config.system_prompt``.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from langchain.agents.middleware import AgentMiddleware

from pyharness import Service

from .config import MODES, SKILLS_MOUNT, LoopConfig, PresetConfig
from .graph import build as build_graph


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
            "listener(kwargs: dict, next) before create_deep_agent(**kwargs); "
            "listeners edit kwargs and return `await next()`.",
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
        """Mount ``directory`` (``<skill>/SKILL.md`` layout) read-only at ``/skills/<label>/`` for ``presets``
        (``None``: all); returns the disposer."""
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
            {
                "label": s,
                "path": str(p),
                "mount": f"{SKILLS_MOUNT}/{s}/",
                "owner": o,
                "presets": list(pr) if pr else None,
            }
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

    # ------------------------------------------------------------------ build
    async def build(self, workspace: str | None = None, mode: str | None = None, preset: str | None = None) -> Any:
        """Graph for a workspace root (``None``: the default), a permission mode and an agent preset."""
        return await build_graph(self, workspace, mode, preset)
