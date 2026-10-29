"""``plugin_manager`` tool and the plugin-authoring prompt section.

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
from pathlib import Path
from typing import Any, Literal

from langchain.tools import ToolRuntime
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from pyharness import manage

name = "pyharness-plugin-manager"
inject = ["tools", "prompt"]

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
    guidance: bool = Field(True, description="Plugin-authoring section in the system prompt.")


GUIDANCE = """\
## Extending this harness
Plugins are Python distributions with two entry points: `pyharness.plugins` (code) and
`pyharness.bundles` (mount position in the configuration tree).

Workflow:
1. `harness_inspect`: live API; services and methods, events and dispatch modes, config schemas, tools, routes.
2. `plugin_manager action=template target=<name>`: starter files, written to the workspace under `/plugins/<name>/`.
3. `plugin_manager action=install_bundle target=/plugins/<name>`: install into this profile; preflighted in a separate process.
   - rejected: errors returned; the profile is unchanged.
   - saved: the harness restarts after this turn; this session continues in the new generation.
4. New generation: the new capability is verified.

Rules:
- Profile files change only through plugin_manager.
- Mutating plugin_manager actions require the user's approval.
- A turn with a saved change ends with a one-line status."""


TEMPLATE_FILES: dict[str, str] = {
    "pyproject.toml": """\
[project]
name = "__DIST__"
version = "0.1.0"
description = "__TITLE__"
requires-python = ">=3.12"
# Provided by the harness: pyharness-core, pydantic, langchain-core, fastapi.
dependencies = []

[project.entry-points."pyharness.plugins"]
__DIST__ = "__MODULE__"

[project.entry-points."pyharness.bundles"]
__BUNDLE__ = "__MODULE__:BUNDLE"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["__MODULE__"]
""",
    "__MODULE__/__init__.py": '''\
"""__TITLE__."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel

name = "__DIST__"
# Required services; the plugin starts once all exist.
inject = ["tools"]

# Mount position in the configuration tree.
BUNDLE = Path(__file__).with_name("bundle.yaml")


class Config(BaseModel):
    greeting: str = "hello"


def apply(ctx: Any, config: Config) -> None:
    def greet(person: str) -> str:
        """Greeting for a person."""
        return f"{config.greeting}, {person}!"

    # Registrations through ctx are undone when the plugin stops.
    ctx.tools.register(greet)

    # tools/result (parallel): each finished tool call.
    # @ctx.on("tools/result")
    # async def audit(call, result):
    #     ctx.logger.info("tool %s finished", call.name)

    # HTTP routes, with "http" in `inject`:
    # from fastapi import APIRouter
    # router = APIRouter()
    # @router.get("/status")
    # async def status() -> dict:
    #     return {"ok": True}
    # ctx.http.include_router(router, prefix="/__BUNDLE__")
''',
    "__MODULE__/bundle.yaml": """\
title: __TITLE__
description: __TITLE__
patch:
  - id: __BUNDLE__
    name: __DIST__
    config:
      greeting: hello
""",
}


def render_template(short: str) -> dict[str, str]:
    slug = re.sub(r"[^a-z0-9]+", "-", short.lower()).strip("-") or "my-plugin"
    module = "pyh_" + slug.replace("-", "_")
    dist = f"pyh-{slug}"
    title = slug.replace("-", " ").title() + " plugin"
    out = {}
    for path, text in TEMPLATE_FILES.items():
        for token, value in (("__DIST__", dist), ("__MODULE__", module), ("__BUNDLE__", slug), ("__TITLE__", title)):
            text = text.replace(token, value)
            path = path.replace(token, value)
        out[path] = text
    return out


def apply(ctx: Any, config: Config) -> None:
    if config.guidance:
        ctx.prompt.add("plugin-authoring", GUIDANCE, order=50)

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
            result["next"] = (
                "Saved. Restart after this turn; this session continues in the new generation. "
                "Turn end: one-line status."
            )
        else:
            result["application"] = "saved-restart-required"
            result["next"] = "Saved. Unsupervised harness: the change applies on the next start (`pyh run` supervises restarts)."
        return result

    async def plugin_manager(
        runtime: ToolRuntime,
        action: Action,
        target: str | None = None,
        enabled: bool | None = None,
    ) -> str:
        """Plugins and bundles of this harness profile.

        action                                              effect
        list                                                entries with state; installed bundles
        template target=<name>                              starter bundle files
        install_bundle target=<dir>                         install a bundle from a workspace directory
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
                    {k: e.get(k) for k in ("id", "name", "state", "source", "missing", "error") if e.get(k)} for e in baseline
                ],
                "bundles": profile.installed_bundles(),
                "generation": ctx.lifecycle.generation,
            }
        elif action == "template":
            files = render_template(target or "my-plugin")
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
            result = finish(await manage.install_bundle(profile, path, baseline=baseline), f"install bundle from {target}", session_id)
        elif action == "uninstall_bundle":
            if not target:
                return json.dumps({"error": "uninstall_bundle: target=<bundle> required"})
            result = finish(await manage.uninstall_bundle(profile, target, baseline=baseline), f"uninstall bundle {target}", session_id)
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
