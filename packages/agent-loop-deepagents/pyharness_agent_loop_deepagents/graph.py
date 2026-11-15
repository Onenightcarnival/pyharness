from __future__ import annotations

from pathlib import Path
from string import Template
from typing import Any

from deepagents import FilesystemPermission, create_deep_agent
from deepagents.backends import BackendProtocol, CompositeBackend, FilesystemBackend, StateBackend
from deepagents.backends.protocol import FileDownloadResponse, GlobResult, GrepResult, LsResult, ReadResult
from deepagents.middleware.subagents import GENERAL_PURPOSE_SUBAGENT
from langchain.agents.middleware import AgentMiddleware

from pyharness import package_prompts
from pyharness_llm import LLMConfigError

from .config import MODES, LoopConfig, PresetConfig
from .middleware import HarnessMiddleware

PROMPTS = package_prompts(__file__)


class MountDirectory(BackendProtocol):
    """Directory without a file of its own: the parent of mounts."""

    def ls(self, path: str) -> LsResult:
        return LsResult(entries=[])

    def read(self, file_path: str, offset: int = 0, limit: int = 2000) -> ReadResult:
        return ReadResult(error=f"File '{file_path}' not found")

    def grep(
        self, pattern: str, path: str | None = None, glob: str | None = None, *, max_count: int | None = None
    ) -> GrepResult:
        return GrepResult(matches=[])

    def glob(self, pattern: str, path: str | None = None) -> GlobResult:
        return GlobResult(matches=[])

    def download_files(self, paths: list[str]) -> list[FileDownloadResponse]:
        return [FileDownloadResponse(path=path, error="file_not_found") for path in paths]


def mount_tree(mounts: list[tuple[list[str], Path]]) -> Any:
    """
    Backend for ``mounts`` (``(path segments, directory)``): each directory at its segments, and every directory
    above it listing the mounts below.
    """
    here = [directory for parts, directory in mounts if not parts]
    default = FilesystemBackend(root_dir=here[0], virtual_mode=True) if here else MountDirectory()
    below: dict[str, list[tuple[list[str], Path]]] = {}
    for parts, directory in mounts:
        if parts:
            below.setdefault(parts[0], []).append((parts[1:], directory))
    if not below:
        return default
    return CompositeBackend(default=default, routes={f"/{name}/": mount_tree(sub) for name, sub in below.items()})


def route_of(mount: str) -> str:
    """Composite route of a mount: its first path segment."""
    return "/" + mount.strip("/").split("/")[0] + "/"


def backend_and_skills(
    ctx: Any,
    config: LoopConfig,
    skills: list[tuple[str, Path]],
    mounts: list[tuple[str, Path, bool]],
    workspace: str | None,
    mode: str,
) -> tuple[Any, list[str], list[Any]]:
    """
    Backend for the workspace and mode with the ``skills`` (``(virtual path, directory)``) and ``mounts``
    (``(virtual path, directory, writable)``) routed in, the skill sources, and the write-deny rules: skills and
    mounts are read-only unless ``writable``. A mount's first path segment is one route: the directories above a
    mount list the mounts below and hold nothing else.
    """
    workspaces = ctx.get("workspace", None)
    if workspaces is not None and hasattr(workspaces, "backend_for"):
        backend = workspaces.backend_for(workspace, shell=mode != "read-only")
    else:
        backend = ctx.get("backend", None)
    sources = [*(config.skills or []), *(mount for mount, _ in skills)]
    rules: list[Any] = []
    if mode == "read-only":
        rules.append(FilesystemPermission(operations=["write"], paths=["/", "/**"], mode="deny"))
    if not skills and not mounts:
        return backend, sources, rules
    routes: dict[str, Any] = {}
    if mounts:
        routes.update(mount_tree([(mount.strip("/").split("/"), path) for mount, path, _ in mounts]).routes)
    routes.update({mount: FilesystemBackend(root_dir=path, virtual_mode=True) for mount, path in skills})
    # Deny rules lie under composite routes: such rules are accepted even when the workspace backend runs commands.
    # A route is denied as a whole; one that holds a writable mount is denied mount by mount.
    open_routes = {route_of(mount) for mount, _, writable in mounts if writable}
    read_only = [
        mount if route_of(mount) in open_routes else route_of(mount) for mount, _, writable in mounts if not writable
    ]
    rules.extend(
        FilesystemPermission(operations=["write"], paths=[path, f"{path}**"], mode="deny")
        for path in dict.fromkeys([*read_only, *(mount for mount, _ in skills)])
    )
    composite = CompositeBackend(default=backend if backend is not None else StateBackend(), routes=routes)
    return composite, sources, rules


def resolve_subagent(ctx: Any, spec: dict[str, Any], registry: dict[str, Any]) -> dict[str, Any]:
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
        spec["model"] = ctx.llm.resolve(spec["model"])
    return spec


def built_model(ctx: Any, config: LoopConfig) -> tuple[str | None, Any]:
    """
    Model the graph is built with. An unusable default falls back to ``echo:echo`` so the harness boots;
    requests then resolve the configured model and report its error in the session.
    """
    spec = config.model or ctx.llm.default
    try:
        return spec, ctx.llm.resolve(spec)
    except LLMConfigError as exc:
        if ctx.lifecycle.preflight or "echo" not in ctx.llm.providers():
            raise
        ctx.logger.warning(
            "default model %s unusable at boot (%s); built with echo:echo, requests resolve the configured model",
            spec,
            exc,
        )
        return "echo:echo", ctx.llm.resolve("echo:echo")


async def build(
    ctx: Any,
    config: LoopConfig,
    *,
    mode: str,
    preset: tuple[str, PresetConfig],
    skills: list[tuple[str, Path]],
    mounts: list[tuple[str, Path, bool]],
    subagents: list[dict[str, Any]],
    middleware: list[AgentMiddleware],
    workspace: str | None = None,
) -> Any:
    """
    Graph for a workspace root (``None``: the default), a permission mode id, a ``(id, config)`` preset, the
    ``skills`` and ``mounts`` of that preset, and the subagent specs and middleware added by plugins.
    """
    preset_id, preset_cfg = preset
    keep = set(preset_cfg.tools) if preset_cfg.tools is not None else None
    drop = set(preset_cfg.exclude_tools)
    tools = [t for t in ctx.tools.list() if (keep is None or t.name in keep) and t.name not in drop]
    if mode == "read-only":  # tools tagged `shell` (the persistent bash, background commands) stay out
        shell_tools = {r.tool.name for r in ctx.tools.records() if "shell" in r.tags}
        tools = [t for t in tools if t.name not in shell_tools]
    registry = {t.name: t for t in tools}
    subagents = [resolve_subagent(ctx, s, registry) for s in [*config.subagents, *subagents]]
    # Every declarative subagent, the general-purpose one included, carries HarnessMiddleware.
    if not any(s.get("name") == GENERAL_PURPOSE_SUBAGENT["name"] for s in subagents):
        subagents.insert(0, dict(GENERAL_PURPOSE_SUBAGENT))
    built_spec, model = built_model(ctx, config)
    for spec in subagents:
        if "runnable" in spec or "graph_id" in spec:
            continue  # compiled and remote subagents keep their own middleware
        spec["middleware"] = [HarnessMiddleware(ctx, built_spec), *spec.get("middleware", [])]
    workspaces = ctx.get("workspace", None)
    ws = workspaces.open(workspace) if workspaces is not None and hasattr(workspaces, "open") else workspaces
    permissions = ws.permissions() if ws is not None and hasattr(ws, "permissions") else []
    backend, sources, rules = backend_and_skills(ctx, config, skills, mounts, workspace, mode)
    permissions = [*permissions, *rules]
    interrupt_on = {} if mode == "full-access" else {**ctx.tools.interrupt_on(), **config.interrupt_on}
    root = ws.root if ws is not None and hasattr(ws, "root") else "(none)"
    policy = Template(PROMPTS["graph"]["session_policy"]).substitute(
        mode_title=MODES[mode]["title"],
        mode_description=MODES[mode]["description"],
        preset_title=preset_cfg.title,
        root=root,
    )
    kwargs: dict[str, Any] = {
        "model": model,
        "tools": tools,
        "system_prompt": ctx.prompt.render(preset_id) + "\n\n" + policy,
        "middleware": [HarnessMiddleware(ctx, built_spec), *middleware],
        "checkpointer": ctx.get("checkpointer"),
        "store": ctx.get("store", None),
        "backend": backend,
        "interrupt_on": interrupt_on or None,
        "subagents": subagents or None,
        "permissions": permissions or None,
        "skills": sources or None,
        "memory": config.memory,
        "name": "pyharness",
    }
    kwargs = await ctx.waterfall("agent-loop/build", kwargs, final=lambda kw: kw)
    return create_deep_agent(**{k: v for k, v in kwargs.items() if v is not None})
