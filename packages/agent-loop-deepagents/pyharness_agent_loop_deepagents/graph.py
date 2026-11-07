"""Graph building: the backend with its skills mounts, the write-deny rules, subagent resolution, ``create_deep_agent``.

| function                 | contract                                                                        |
|--------------------------|---------------------------------------------------------------------------------|
| ``backend_and_skills()`` | backend for the workspace and mode, the skill sources, the write-deny rules      |
| ``resolve_subagent()``   | tool names → registered tools, model spec → model, inside one subagent spec      |
| ``built_model()``        | ``(spec, model)`` the graph is built with; ``echo:echo`` when the default is unusable at |
|                          | boot                                                                            |
| ``build()``              | the compiled deepagents graph for a workspace, a permission mode and a preset    |

Skills directories added by plugins are mounted read-only for the model at ``/skills/<label>/``
(``CompositeBackend`` route over ``ctx.backend``); deepagents lists them in the system prompt and
the model reads a skill with ``read_file``.

``agent-loop/build`` (waterfall) receives the ``create_deep_agent`` keyword arguments.
"""

from __future__ import annotations

from string import Template
from typing import TYPE_CHECKING, Any

from deepagents import FilesystemPermission, create_deep_agent
from deepagents.backends import CompositeBackend, FilesystemBackend, StateBackend
from deepagents.middleware.subagents import GENERAL_PURPOSE_SUBAGENT

from pyharness import package_prompts
from pyharness_llm import LLMConfigError

from .config import MODES, SKILLS_MOUNT
from .middleware import HarnessMiddleware

if TYPE_CHECKING:
    from .service import DeepAgentsLoop

PROMPTS = package_prompts(__file__)


def backend_and_skills(
    loop: DeepAgentsLoop, workspace: str | None, mode: str, preset: str
) -> tuple[Any, list[str], list[Any]]:
    """Backend for the workspace and mode with the preset's skills routes, the skill sources, and the write-deny
    rules."""
    workspaces = loop.ctx.get("workspace", None)
    if workspaces is not None and hasattr(workspaces, "backend_for"):
        backend = workspaces.backend_for(workspace, shell=mode != "read-only")
    else:
        backend = loop.ctx.get("backend", None)
    sources = list(loop.config.skills or [])
    rules: list[Any] = []
    if mode == "read-only":
        rules.append(FilesystemPermission(operations=["write"], paths=["/", "/**"], mode="deny"))
    mounts = [(s, p) for s, p, _, presets in loop._skills if presets is None or preset in presets]
    if not mounts:
        return backend, sources, rules
    routes: dict[str, Any] = {}
    for slug, path in mounts:
        mount = f"{SKILLS_MOUNT}/{slug}/"
        routes[mount] = FilesystemBackend(root_dir=path, virtual_mode=True)
        sources.append(mount)
        # One deny rule per mount: rules scoped to composite routes are accepted even when the workspace backend
        # runs commands.
        rules.append(FilesystemPermission(operations=["write"], paths=[mount, f"{mount}**"], mode="deny"))
    composite = CompositeBackend(default=backend if backend is not None else StateBackend(), routes=routes)
    return composite, sources, rules


def resolve_subagent(loop: DeepAgentsLoop, spec: dict[str, Any], registry: dict[str, Any]) -> dict[str, Any]:
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
        spec["model"] = loop.ctx.llm.resolve(spec["model"])
    return spec


def built_model(loop: DeepAgentsLoop) -> tuple[str | None, Any]:
    """Model the graph is built with. An unusable default falls back to ``echo:echo`` so the harness boots;
    requests then resolve the configured model and report its error in the session."""
    spec = loop.config.model or loop.ctx.llm.default
    try:
        return spec, loop.ctx.llm.resolve(spec)
    except LLMConfigError as exc:
        if loop.ctx.lifecycle.preflight or "echo" not in loop.ctx.llm.providers():
            raise
        loop.ctx.logger.warning(
            "default model %s unusable at boot (%s); built with echo:echo, requests resolve the configured model",
            spec,
            exc,
        )
        return "echo:echo", loop.ctx.llm.resolve("echo:echo")


async def build(
    loop: DeepAgentsLoop, workspace: str | None = None, mode: str | None = None, preset: str | None = None
) -> Any:
    """Graph for a workspace root (``None``: the default), a permission mode and an agent preset."""
    ctx = loop.ctx
    mode = loop.mode(mode)
    preset_id, preset_cfg = loop.preset(preset)
    keep = set(preset_cfg.tools) if preset_cfg.tools is not None else None
    drop = set(preset_cfg.exclude_tools)
    tools = [t for t in ctx.tools.list() if (keep is None or t.name in keep) and t.name not in drop]
    if mode == "read-only":  # tools tagged `shell` (the persistent bash, background commands) stay out
        shell_tools = {r.tool.name for r in ctx.tools.records() if "shell" in r.tags}
        tools = [t for t in tools if t.name not in shell_tools]
    registry = {t.name: t for t in tools}
    subagents = [resolve_subagent(loop, s, registry) for s in loop.config.subagents]
    subagents += [resolve_subagent(loop, s, registry) for s, _ in loop._subagents]
    # Every declarative subagent, the general-purpose one included, carries HarnessMiddleware.
    if not any(s.get("name") == GENERAL_PURPOSE_SUBAGENT["name"] for s in subagents):
        subagents.insert(0, dict(GENERAL_PURPOSE_SUBAGENT))
    built_spec, model = built_model(loop)
    for spec in subagents:
        if "runnable" in spec or "graph_id" in spec:
            continue  # compiled and remote subagents keep their own middleware
        spec["middleware"] = [HarnessMiddleware(ctx, built_spec), *spec.get("middleware", [])]
    workspaces = ctx.get("workspace", None)
    ws = workspaces.open(workspace) if workspaces is not None and hasattr(workspaces, "open") else workspaces
    permissions = ws.permissions() if ws is not None and hasattr(ws, "permissions") else []
    backend, skills, rules = backend_and_skills(loop, workspace, mode, preset_id)
    permissions = [*permissions, *rules]
    interrupt_on = {} if mode == "full-access" else {**ctx.tools.interrupt_on(), **loop.config.interrupt_on}
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
        "middleware": [HarnessMiddleware(ctx, built_spec), *(m for m, _ in loop._middleware)],
        "checkpointer": ctx.get("checkpointer"),
        "store": ctx.get("store", None),
        "backend": backend,
        "interrupt_on": interrupt_on or None,
        "subagents": subagents or None,
        "permissions": permissions or None,
        "skills": skills or None,
        "memory": loop.config.memory,
        "name": "pyharness",
    }
    kwargs = await ctx.waterfall("agent-loop/build", kwargs, final=lambda kw: kw)
    return create_deep_agent(**{k: v for k, v in kwargs.items() if v is not None})
