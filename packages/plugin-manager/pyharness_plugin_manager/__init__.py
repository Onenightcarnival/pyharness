"""``plugin_manager`` tool, the plugin-authoring skills, and the short prompt section.

| config       | effect                                                                                   |
|--------------|------------------------------------------------------------------------------------------|
| ``guidance`` | three-line section in the system prompt for the presets without the skills (``standard``) |
| ``skills``   | ``skills/`` of this package mounted at ``/skills/pyharness/`` for the ``creator`` preset |

Skills (``skills/<name>/SKILL.md``): ``pyharness-plugin-development``, ``editing-pyharness-compositions``,
``pyharness-composition-reference``, ``agent-experience``.
Templates: ``skills/pyharness-plugin-development/templates/``.

| step                | effect                                                                    |
|---------------------|---------------------------------------------------------------------------|
| mutating action     | :mod:`pyharness.manage` transaction: change → preflight → keep or restore |
| rejected            | errors returned; profile unchanged                                        |
| saved, supervised   | restart after the current turn; the calling session continues             |
| saved, unsupervised | change applies on the next start                                          |

Mutating actions wait for human approval (``when`` predicate on the tool's gate).
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from pathlib import Path
from textwrap import dedent
from typing import Any, Literal

from langchain.tools import ToolRuntime
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from pyharness import manage

name = "pyharness-plugin-manager"
inject = ["tools", "prompt", "agentLoop"]

SKILLS_DIR = Path(__file__).with_name("skills")
TEMPLATES_DIR = SKILLS_DIR / "pyharness-plugin-development" / "templates"
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
    skills_presets: list[str] = Field(
        default_factory=lambda: ["creator"], description="Agent presets that see the skills."
    )


GUIDANCE = dedent(
    """
    ## Extending this harness
    Plugins are Python distributions mounted in this profile's configuration tree. `harness_inspect` shows the live API;
    `plugin_manager` writes starter files, installs bundles (approval, preflight in a separate process, restart after
    the turn) and toggles entries; profile files change only through it. The Creator preset adds skills with the full
    procedure.
    """
).strip()


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
    """Template files for a bundle named after ``short``; ``__DIST__``-style tokens substituted in paths and
    contents.
    """
    slug = re.sub(r"[^a-z0-9]+", "-", short.lower()).strip("-") or "my-plugin"
    module = "pyh_" + slug.replace("-", "_")
    dist = f"pyh-{slug}"
    title = slug.replace("-", " ").title() + " plugin"
    values = dict(zip(TOKENS, (dist, module, slug, title), strict=True))
    out = {}
    for path, text in _template_files(variant):
        for token, value in values.items():
            text = text.replace(token, value)
            path = path.replace(token, value)
        out[path] = text
    return out


def apply(ctx: Any, config: Config) -> None:
    if config.skills:
        ctx.agentLoop.add_skills(SKILLS_DIR, "pyharness", presets=config.skills_presets)
    if config.guidance:
        presets = ctx.agentLoop.preset_ids()
        without_skills = [p for p in presets if p not in config.skills_presets] if config.skills else None
        if without_skills or not config.skills:
            ctx.prompt.add("plugin-authoring", GUIDANCE, order=50, presets=without_skills or None)

    def session_of(runtime: Any) -> str | None:
        try:
            return (runtime.config.get("configurable") or {}).get("thread_id")
        except Exception:
            return None

    def resolve_path(target: str) -> Path:
        workspace = ctx.get("workspace", None)
        return workspace.resolve(target) if workspace is not None else Path(target).expanduser()

    def finish(result: dict[str, Any], reason: str, session_id: str | None) -> dict[str, Any]:
        if result.get("application") != "saved":
            return result
        lifecycle = ctx.lifecycle
        if lifecycle.supervised:
            lifecycle.request_restart(reason, resume=[session_id] if session_id else [])
            result["application"] = "restart-scheduled"
            result["next"] = dedent(
                """
                Saved. Restart after this turn; this session continues in the new generation.
                Turn end: one-line status.
                """
            ).strip()
        else:
            result["application"] = "saved-restart-required"
            result["next"] = (
                "Saved. Unsupervised harness: the change applies on the next start (`pyh run` supervises restarts)."
            )
        return result

    async def plugin_manager(
        runtime: ToolRuntime,
        action: Action,
        target: str | None = None,
        enabled: bool | None = None,
        variant: str | None = None,
    ) -> str:
        """Plugins and bundles of this harness profile.

        action                                              effect
        list                                                entries with state; installed bundles
        template target=<name> [variant=basic|tool-and-route|ui-panel] starter bundle files; variant default basic
        install_bundle target=<dir | package>               install a bundle from a workspace directory or PyPI
        uninstall_bundle target=<bundle>                    remove an installed bundle
        set_bundle_enabled target=<bundle> enabled=<bool>   enable or disable a bundle
        set_plugin_enabled target=<entry id> enabled=<bool> enable or disable an entry
        restart                                             restart after this turn

        Mutations are preflighted in a separate process; a rejected mutation changes nothing.
        """
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
            path = resolve_path(target)
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

    tool = StructuredTool.from_function(coroutine=plugin_manager, name="plugin_manager")
    approval: Any = False
    if config.require_approval:
        approval = {
            "allowed_decisions": ["approve", "reject"],
            "description": "Plugin change for this profile. Installed code runs in the harness process.",
            "when": lambda request: (request.tool_call.get("args") or {}).get("action") in MUTATING,
        }
    ctx.tools.register(tool, approval=approval)


__all__ = [
    "Action",
    "Config",
    "MUTATING",
    "SKILLS_DIR",
    "TEMPLATES_DIR",
    "TOKENS",
    "apply",
    "inject",
    "name",
    "render_template",
    "template_variants",
]
