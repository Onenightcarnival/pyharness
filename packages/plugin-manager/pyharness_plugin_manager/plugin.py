from __future__ import annotations

import json
import re
from collections.abc import Iterator
from pathlib import Path
from string import Template
from typing import Any, Literal

from langchain.tools import ToolRuntime
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

import pyharness
from pyharness import manage, package_prompts, package_root

PROMPTS = package_prompts(__file__)

name = "pyxis-harness-plugin-manager"
doc = "``plugin_manager`` tool, the plugin-authoring skills, the package and plugin-source mounts, the prompt sections."
inject = ["tools", "prompt", "agentLoop"]

SKILLS_DIR = Path(__file__).with_name("skills")
TEMPLATES_DIR = SKILLS_DIR / "pyxis-harness-plugin-development" / "templates"
SOURCES_MOUNT = "/harness"
PLUGINS_MOUNT = "/plugins"
PLUGINS_DIR = "plugins"  # under the profile's Documents directory
TOKENS = ("__DIST__", "__MODULE__", "__BUNDLE__", "__TITLE__")

Action = Literal[
    "list",
    "template",
    "install_bundle",
    "uninstall_bundle",
    "set_bundle_enabled",
    "set_plugin_enabled",
    "restart",
]
MUTATING = {"install_bundle", "uninstall_bundle", "set_bundle_enabled", "set_plugin_enabled", "restart"}


class Config(BaseModel):
    require_approval: bool = Field(True, description="Human approval for each mutating action.")
    guidance: bool = Field(
        True, description="Short plugin-authoring section in the system prompt of presets without the skills."
    )
    skills: bool = Field(
        True,
        description="Mount the plugin-authoring skills at /skills/pyharness/ for the presets listed in skills_presets.",
    )
    sources: bool = Field(
        True,
        description="Mount every loaded package read-only at /harness/<module>/ for the presets in skills_presets.",
    )
    skills_presets: list[str] = Field(
        default_factory=lambda: ["creator"],
        description="Agent presets that see the skills, the package sources and the profile's plugin sources.",
    )


GUIDANCE: str = PROMPTS["plugin_manager"]["GUIDANCE"]
SOURCES: str = PROMPTS["plugin_manager"]["SOURCES"]
PLUGINS: str = PROMPTS["plugin_manager"]["PLUGINS"]


def source_roots(ctx: Any) -> dict[str, Path]:
    """Kernel and every loaded plugin package: ``module name -> directory of its files``."""
    module_dirs = [Path(pyharness.__file__).resolve().parent]
    module_dirs += [Path(rt.spec.package_dir) for rt in ctx.loader.runtimes if rt.spec and rt.spec.package_dir]
    roots: dict[str, Path] = {}
    for module_dir in module_dirs:
        roots.setdefault(module_dir.name, package_root(module_dir))
    return roots


def template_variants() -> list[str]:
    return sorted(p.name for p in TEMPLATES_DIR.iterdir() if p.is_dir())


def _template_files(variant: str) -> Iterator[tuple[str, str]]:
    root = TEMPLATES_DIR / variant
    if not root.is_dir():
        raise ValueError(f"unknown template {variant!r}; variants: {', '.join(template_variants())}")
    for path in sorted(root.rglob("*")):
        if path.is_file():
            yield path.relative_to(root).as_posix(), path.read_text(encoding="utf-8")


def render_template(short: str, variant: str = "basic") -> dict[str, str]:
    """
    Template files for a bundle named after ``short``; ``__DIST__``-style tokens substituted in paths and
    contents.
    """
    slug = re.sub(r"[^a-z0-9]+", "-", short.lower()).strip("-") or "my-plugin"
    module = "pyh_" + slug.replace("-", "_")
    dist = f"pyh-{slug}"
    title = slug.replace("-", " ").title() + " plugin"
    values = dict(zip(TOKENS, (dist, module, slug, title), strict=True))
    out = {}
    for template_path, template in _template_files(variant):
        path, text = template_path, template
        for token, value in values.items():
            text = text.replace(token, value)
            path = path.replace(token, value)
        out[path] = text
    return out


def apply(ctx: Any, config: Config) -> None:
    if config.skills:
        ctx.agentLoop.add_skills(SKILLS_DIR, "pyharness", presets=config.skills_presets)
    if config.sources:
        for module, root in source_roots(ctx).items():
            ctx.agentLoop.add_mount(f"{SOURCES_MOUNT}/{module}", root, presets=config.skills_presets)
        ctx.prompt.add("harness-sources", SOURCES, order=55, presets=config.skills_presets or None)
    profile = ctx.get("profile", None)
    if profile is not None:
        plugins = profile.documents / PLUGINS_DIR
        plugins.mkdir(parents=True, exist_ok=True)
        ctx.agentLoop.add_mount(PLUGINS_MOUNT, plugins, presets=config.skills_presets, writable=True)
        section = Template(PLUGINS).substitute(path=plugins)
        ctx.prompt.add("plugin-sources", section, order=56, presets=config.skills_presets or None)
    if config.guidance:
        presets = ctx.agentLoop.preset_ids()
        without_skills = [p for p in presets if p not in config.skills_presets] if config.skills else None
        if without_skills or not config.skills:
            ctx.prompt.add("plugin-authoring", GUIDANCE, order=50, presets=without_skills or None)

    def session_of(runtime: Any) -> str | None:
        try:
            return (runtime.config.get("configurable") or {}).get("thread_id")
        except AttributeError:
            return None

    async def resolve_path(target: str, session_id: str | None) -> Path:
        """Path on disk of an install target: inside a mount, else in the session's workspace."""
        mounted = ctx.agentLoop.mount_target(target)
        if mounted is not None:
            return mounted
        workspaces = ctx.get("workspace", None)
        if workspaces is None:
            return Path(target).expanduser()
        agents = ctx.get("agents", None)
        record = await agents.get_session(session_id) if agents is not None and session_id else None
        return workspaces.open((record or {}).get("workspace")).resolve(target)

    def finish(result: dict[str, Any], reason: str, session_id: str | None) -> dict[str, Any]:
        if result.get("application") != "saved":
            return result
        lifecycle = ctx.lifecycle
        if lifecycle.supervised:
            lifecycle.request_restart(reason, resume=[session_id] if session_id else [])
            result["application"] = "restart-scheduled"
            result["next"] = PROMPTS["plugin_manager"]["restart_scheduled"]
        else:
            result["application"] = "saved-restart-required"
            result["next"] = PROMPTS["plugin_manager"]["saved_restart_required"]
        return result

    async def plugin_manager(
        runtime: ToolRuntime,
        action: Action,
        target: str | None = None,
        enabled: bool | None = None,
        variant: str | None = None,
    ) -> str:
        profile = ctx.get("profile", None)
        if profile is None:
            return json.dumps({"error": "no profile: plugin management unavailable"})
        session_id = session_of(runtime)
        baseline = ctx.loader.snapshot()
        result: dict[str, Any]
        if action == "list":
            result = {
                "entries": [
                    {k: e.get(k) for k in ("id", "name", "state", "source", "missing", "error") if e.get(k)}
                    for e in baseline
                ],
                "bundles": profile.installed_bundles(),
                "generation": ctx.lifecycle.generation,
            }
        elif action == "template":
            try:
                files = render_template(target or "my-plugin", variant or "basic")
            except ValueError as exc:
                return json.dumps({"error": str(exc)})
            root = f"/plugins/{(target or 'my-plugin').strip('/')}"
            result = {
                "write_under": root,
                "files": files,
                "then": f"plugin_manager action=install_bundle target={root}",
            }
        elif action == "install_bundle":
            if not target:
                return json.dumps({"error": "install_bundle: target=<directory> required"})
            path = await resolve_path(target, session_id)
            if manage.looks_like_path(target) or Path(str(path)).exists():
                result = finish(
                    await manage.install_bundle(profile, path, baseline=baseline),
                    f"install bundle from {target}",
                    session_id,
                )
            else:
                result = finish(
                    await manage.install_package(profile, target, baseline=baseline),
                    f"install package {target}",
                    session_id,
                )
        elif action == "uninstall_bundle":
            if not target:
                return json.dumps({"error": "uninstall_bundle: target=<bundle> required"})
            result = finish(
                await manage.uninstall_bundle(profile, target, baseline=baseline),
                f"uninstall bundle {target}",
                session_id,
            )
        elif action == "set_bundle_enabled":
            if not target or enabled is None:
                return json.dumps({"error": "set_bundle_enabled: target and enabled required"})
            result = finish(
                await manage.set_bundle_enabled(profile, target, enabled, baseline=baseline),
                f"{'enable' if enabled else 'disable'} bundle {target}",
                session_id,
            )
        elif action == "set_plugin_enabled":
            if not target or enabled is None:
                return json.dumps({"error": "set_plugin_enabled: target and enabled required"})
            result = finish(
                await manage.set_entry_enabled(profile, target, enabled, baseline=baseline),
                f"{'enable' if enabled else 'disable'} entry {target}",
                session_id,
            )
        elif action == "restart":
            result = finish({"application": "saved"}, "restart requested by the agent", session_id)
        else:  # pragma: no cover
            result = {"error": f"unknown action {action}"}
        return json.dumps(result, ensure_ascii=False, indent=1, default=str)

    tool = StructuredTool.from_function(
        coroutine=plugin_manager, name="plugin_manager", description=PROMPTS["tools"]["plugin_manager"]
    )
    approval: Any = False
    if config.require_approval:
        approval = {
            "allowed_decisions": ["approve", "reject"],
            "description": "Plugin change for this profile. Installed code runs in the harness process.",
            "when": lambda request: (request.tool_call.get("args") or {}).get("action") in MUTATING,
        }
    ctx.tools.register(tool, approval=approval)
