from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path
from textwrap import dedent
from typing import Any, ClassVar

from langchain.agents.middleware import AgentMiddleware

from pyxis_harness import Service

from .config import MODES, SKILLS_MOUNT, LoopConfig, Mode, PresetConfig
from .graph import build as build_graph


class DeepAgentsLoop(Service):
    """deepagents graph built from the services of other plugins."""

    key = "agentLoop"
    name = "pyxis-harness-agent-loop-deepagents"
    inject: ClassVar[list[str]] = ["llm", "tools", "prompt", "checkpointer"]
    Config = LoopConfig

    def __init__(self, ctx: Any, config: LoopConfig) -> None:
        super().__init__(ctx, config)
        self._subagents: list[tuple[dict[str, Any], str]] = []
        self._middleware: list[tuple[AgentMiddleware, str]] = []
        self._skills: list[tuple[str, Path, str, tuple[str, ...] | None]] = []  # (label, directory, owner, presets)
        # (mount, directory, owner, presets, writable)
        self._mounts: list[tuple[str, Path, str, tuple[str, ...] | None, bool]] = []
        self._presets: dict[str, tuple[PresetConfig, str]] = {}  # plugin-added presets: id -> (config, owner)
        self._modes: dict[str, tuple[Mode, str]] = {}  # plugin-added modes: id -> (mode, owner)
        if self.config.default_mode not in MODES:
            raise ValueError(f"unknown default_mode {self.config.default_mode!r}; one of {', '.join(MODES)}")

    async def start(self) -> None:
        self.ctx.define_event(
            "agent/model-request",
            "waterfall",
            "listener(call: ModelCall, next) around each model call; `await next()` returns the ModelResponse.",
        )
        self.ctx.define_event(
            "agent/model-retry",
            "parallel",
            "listener(retry: ModelRetry) before a failed model call is retried by the route's retry policy.",
        )
        self.ctx.define_event(
            "agent-loop/build",
            "waterfall",
            dedent(
                """
                listener(kwargs: dict, next) before create_deep_agent(**kwargs);
                listeners edit kwargs and return `await next()`.
                """
            ).strip(),
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
        """
        Mount ``directory`` (``<skill>/SKILL.md`` layout) read-only at ``/skills/<label>/`` for ``presets``
        (``None``: all); returns the disposer.
        """
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

    def add_mount(
        self, mount: str, directory: str | Path, presets: list[str] | None = None, *, writable: bool = False
    ) -> Any:
        """
        Mount ``directory`` at the virtual path ``mount`` for ``presets`` (``None``: all), read-only unless
        ``writable``; returns the disposer.
        """
        path = Path(directory).expanduser().resolve()
        if not path.is_dir():
            raise ValueError(f"mount directory {path} does not exist")
        parts = [part for part in str(mount).split("/") if part]
        if not parts or any(part in {".", ".."} for part in parts):
            raise ValueError(f"mount path {mount!r} is not a virtual directory path")
        virtual = "/" + "/".join(parts) + "/"
        if virtual.startswith(f"{SKILLS_MOUNT}/"):
            raise ValueError(f"{SKILLS_MOUNT}/ is mounted through add_skills")
        if any(existing == virtual for existing, *_ in self._mounts):
            raise ValueError(f"mount path {virtual!r} is already mounted")
        item = (virtual, path, self.caller.entry_id, tuple(presets) if presets else None, writable)
        self._mounts.append(item)
        return self.caller.on_dispose(lambda: self._mounts.remove(item) if item in self._mounts else None)

    def mounts(self) -> list[dict[str, Any]]:
        """Mounts: ``mount``, ``path``, ``owner``, ``presets``, ``writable``."""
        return [
            {"mount": m, "path": str(p), "owner": o, "presets": list(pr) if pr else None, "writable": w}
            for m, p, o, pr, w in self._mounts
        ]

    def mounted(self, path: str | Path) -> str | None:
        """Virtual path of a path on disk that lies inside a mount; ``None`` outside every mount."""
        real = Path(path).expanduser().resolve()
        for mount, root, *_ in sorted(self._mounts, key=lambda item: len(item[1].parts), reverse=True):
            if real == root or root in real.parents:
                inner = real.relative_to(root).as_posix()
                return mount if inner == "." else mount + inner + ("/" if real.is_dir() else "")
        return None

    def mount_target(self, path: str) -> Path | None:
        """Path on disk of a virtual path that lies inside a mount; ``None`` outside every mount."""
        virtual = "/" + str(path).strip("/") + "/"
        for mount, root, *_ in sorted(self._mounts, key=lambda item: len(item[0]), reverse=True):
            if virtual.startswith(mount):
                real = (root / virtual[len(mount) :]).resolve()
                return real if real == root or root in real.parents else None
        return None

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

    def add_mode(
        self,
        id: str,
        title: str,
        description: str = "",
        *,
        base: str = "workspace-write",
        build: Callable[[dict[str, Any]], dict[str, Any] | None] | None = None,
    ) -> Any:
        """
        Add a permission mode owned by the calling plugin; returns the disposer.

        | argument  | contract                                                                             |
        |-----------|--------------------------------------------------------------------------------------|
        | ``base``  | built-in mode whose file, shell and approval rules the mode keeps                    |
        | ``build`` | edits the ``create_deep_agent`` kwargs of the mode's graphs, before ``agent-loop/build`` |

        A session selects the mode; the default for new sessions stays a built-in mode.
        """
        if id in MODES or id in self._modes:
            raise ValueError(f"permission mode {id!r} already exists")
        if base not in MODES:
            raise ValueError(f"unknown base mode {base!r}; one of {', '.join(MODES)}")
        self._modes[id] = (Mode(id, title, description, base, build), self.caller.entry_id)
        return self.caller.on_dispose(lambda: self._modes.pop(id, None))

    def mode_ids(self) -> list[str]:
        return [*MODES, *self._modes]

    def modes(self) -> list[dict[str, Any]]:
        """Roster for selectors: ``id``, ``title``, ``description``, ``default``, ``builtin``, ``owner``."""
        builtin = [
            {"id": id, **info, "default": id == self.config.default_mode, "builtin": True, "owner": self.ctx.entry_id}
            for id, info in MODES.items()
        ]
        added = [
            {
                "id": id,
                "title": mode.title,
                "description": mode.description,
                "default": False,
                "builtin": False,
                "owner": owner,
            }
            for id, (mode, owner) in self._modes.items()
        ]
        return [*builtin, *added]

    def mode(self, id: str | None) -> str:
        """``id`` or the default mode; unknown ids raise ``ValueError``."""
        id = id or self.config.default_mode
        if id not in MODES and id not in self._modes:
            raise ValueError(f"unknown permission mode {id!r}; one of {', '.join(self.mode_ids())}")
        return id

    def _mode(self, id: str) -> Mode:
        if id in self._modes:
            return self._modes[id][0]
        return Mode(id, MODES[id]["title"], MODES[id]["description"], base=id)

    def set_defaults(self, preset: str | None = None, mode: str | None = None) -> dict[str, str]:
        """Change the defaults for new sessions (live); the settings API persists them."""
        if preset is not None:
            self.config.default_preset = self.preset(preset)[0]
        if mode is not None:
            if self.mode(mode) not in MODES:
                raise ValueError(f"the default permission mode is one of {', '.join(MODES)}; {mode!r} is per session")
            self.config.default_mode = mode
        return {"default_preset": self.config.default_preset, "default_mode": self.config.default_mode}

    # ------------------------------------------------------------------ build
    async def build(self, workspace: str | None = None, mode: str | None = None, preset: str | None = None) -> Any:
        """Graph for a workspace root (``None``: the default), a permission mode and an agent preset."""
        preset_id, preset_cfg = self.preset(preset)
        return await build_graph(
            self.ctx,
            self.config,
            mode=self._mode(self.mode(mode)),
            preset=(preset_id, preset_cfg),
            skills=[
                (f"{SKILLS_MOUNT}/{s}/", p)
                for s, p, _, presets in self._skills
                if presets is None or preset_id in presets
            ],
            mounts=[(m, p, w) for m, p, _, presets, w in self._mounts if presets is None or preset_id in presets],
            subagents=[s for s, _ in self._subagents],
            middleware=[m for m, _ in self._middleware],
            workspace=workspace,
        )
