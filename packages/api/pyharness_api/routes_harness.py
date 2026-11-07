"""Harness-level routes: health, plugin management, restart, MCP server settings, syntax highlighting.

| method | path                         | handler              |
|--------|------------------------------|----------------------|
| GET    | ``/health``                  | ``health``           |
| POST   | ``/plugins/install``         | ``install_plugin``   |
| DELETE | ``/plugins/bundles/{name}``  | ``uninstall_plugin`` |
| PUT    | ``/plugins/bundles/{name}``  | ``toggle_bundle``    |
| PUT    | ``/plugins/entries/{id}``    | ``toggle_entry``     |
| POST   | ``/restart``                 | ``restart_now``      |
| GET    | ``/plugins``                 | ``plugins``          |
| GET    | ``/settings/mcp``            | ``get_mcp_settings`` |
| PUT    | ``/settings/mcp``            | ``put_mcp_settings`` |
| POST   | ``/highlight``               | ``highlight_code``   |
| GET    | ``/highlight.css``           | ``highlight_css``    |
"""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, HTTPException, Response

from pyharness import manage

from .models import EnabledBody, HighlightRequest, InstallBody, MCPSettings


def build_harness_router(ctx: Any) -> APIRouter:
    router = APIRouter()

    @router.get("/health")
    async def health() -> dict[str, Any]:
        lifecycle = ctx.lifecycle
        profile = ctx.get("profile", None)
        llm = ctx.get("llm", None)
        workspace = ctx.get("workspace", None)
        return {
            "ok": True,
            "generation": lifecycle.generation,
            "supervised": lifecycle.supervised,
            "restart_pending": lifecycle.restart_pending,
            "profile": profile.name if profile is not None else None,
            "model": getattr(llm, "default", None) if llm is not None else None,
            "workspace": {"name": workspace.root.name or str(workspace.root), "path": str(workspace.root)}
            if workspace is not None
            else None,
        }

    def plugin_profile() -> Any:
        profile = ctx.get("profile", None)
        if profile is None:
            raise HTTPException(409, "no profile: plugins are read-only in this harness")
        return profile

    def applied(result: dict[str, Any], reason: str) -> dict[str, Any]:
        """Turn a manage result into the API answer: rejected → 422; saved → restart scheduled when supervised."""
        if result.get("application") == "rejected":
            raise HTTPException(422, result.get("error") or f"rejected at {result.get('stage')}")
        if result.get("application") == "saved":
            lifecycle = ctx.lifecycle
            if lifecycle.supervised:
                lifecycle.request_restart(reason)
                result["application"] = "restart-scheduled"
            else:
                result["application"] = "saved-restart-required"
        return result

    @router.post("/plugins/install")
    async def install_plugin(body: InstallBody) -> dict[str, Any]:
        """Install a bundle directory into the profile site; preflight, then restart when supervised."""
        profile = plugin_profile()
        if body.path:
            result = await manage.install_bundle(profile, body.path, baseline=ctx.loader.snapshot())
            return applied(result, f"install bundle from {body.path}")
        result = await manage.install_package(
            profile, body.package or "", index_url=body.index_url, baseline=ctx.loader.snapshot()
        )
        return applied(result, f"install package {body.package}")

    def user_bundles(profile: Any) -> set[str]:
        """Bundles installed into the profile site: the only ones the Web UI may remove."""
        return {b["bundle"] for b in profile.installed_bundles() if b.get("installed") == "profile"}

    def switchable_bundles(profile: Any) -> set[str]:
        """Profile-installed bundles plus optional environment bundles (``optional: true``): the ones the Web UI may
        toggle."""
        return {
            b["bundle"] for b in profile.installed_bundles() if b.get("installed") == "profile" or b.get("optional")
        }

    def require_user_bundle(profile: Any, name: str, *, toggle: bool = False) -> None:
        allowed = switchable_bundles(profile) if toggle else user_bundles(profile)
        if name not in allowed:
            raise HTTPException(
                409,
                f"bundle {name!r} is built in (installed with the environment); only plugins installed into the profile"
                + (" and optional presets" if toggle else "")
                + " can be changed here",
            )

    @router.delete("/plugins/bundles/{name}")
    async def uninstall_plugin(name: str) -> dict[str, Any]:
        profile = plugin_profile()
        require_user_bundle(profile, name)
        result = await manage.uninstall_bundle(profile, name, baseline=ctx.loader.snapshot())
        return applied(result, f"uninstall bundle {name}")

    @router.put("/plugins/bundles/{name}")
    async def toggle_bundle(name: str, body: EnabledBody) -> dict[str, Any]:
        profile = plugin_profile()
        require_user_bundle(profile, name, toggle=True)
        result = await manage.set_bundle_enabled(profile, name, body.enabled, baseline=ctx.loader.snapshot())
        return applied(result, f"{'enable' if body.enabled else 'disable'} bundle {name}")

    @router.put("/plugins/entries/{entry_id}")
    async def toggle_entry(entry_id: str, body: EnabledBody) -> dict[str, Any]:
        profile = plugin_profile()
        entry = next((e for e in ctx.loader.snapshot() if e.get("id") == entry_id), None)
        source = str((entry or {}).get("source") or "")
        if entry is None or not source.startswith("bundle:") or source[len("bundle:") :] not in user_bundles(profile):
            raise HTTPException(
                409,
                f"entry {entry_id!r} is built in; "
                "only entries of plugins installed into the profile can be changed here",
            )
        result = await manage.set_entry_enabled(profile, entry_id, body.enabled, baseline=ctx.loader.snapshot())
        return applied(result, f"{'enable' if body.enabled else 'disable'} entry {entry_id}")

    @router.post("/restart")
    async def restart_now() -> dict[str, Any]:
        """Ask the supervisor for a restart once running turns finish (409 when unsupervised)."""
        lifecycle = ctx.lifecycle
        if not lifecycle.supervised:
            raise HTTPException(409, "unsupervised harness: restart it yourself (pyh run supervises restarts)")
        return {"restart_pending": lifecycle.request_restart("requested from the Web UI")}

    @router.get("/plugins")
    async def plugins() -> dict[str, Any]:
        profile = ctx.get("profile", None)
        return {
            "entries": ctx.loader.snapshot(),
            "bundles": profile.installed_bundles() if profile is not None else [],
        }

    @router.get("/settings/mcp")
    async def get_mcp_settings() -> dict[str, Any]:
        """Configured MCP servers (env and header values masked) with their connection status."""
        mcp = ctx.get("mcp", None)
        if mcp is None:
            raise HTTPException(503, "mcp plugin not mounted")
        return {"servers": mcp.servers()}

    @router.put("/settings/mcp")
    async def put_mcp_settings(body: MCPSettings) -> dict[str, Any]:
        """Replace the MCP server list in the profile patch; masked secrets keep their stored value.
        Restart to apply."""
        mcp = ctx.get("mcp", None)
        if mcp is None:
            raise HTTPException(503, "mcp plugin not mounted")
        from pyharness_mcp import MASK

        current = mcp.config.servers
        servers: dict[str, Any] = {}
        for name, server in body.servers.items():
            data = server.model_dump(exclude_none=True)
            previous = current.get(name)
            for secret in ("env", "headers"):
                values = dict(data.get(secret) or {})
                for key, value in list(values.items()):
                    if value == MASK:
                        kept = (getattr(previous, secret, None) or {}).get(key) if previous is not None else None
                        if kept is None:
                            raise HTTPException(422, f"{secret} {key} of server {name!r}: value required")
                        values[key] = kept
                if values:
                    data[secret] = values
                else:
                    data.pop(secret, None)
            servers[name] = data
        result = await manage.set_entry_config(
            plugin_profile(), "mcp", {"servers": servers}, merge=False, preflight=False
        )
        return applied(result, "MCP servers changed")

    @router.post("/highlight")
    async def highlight_code(body: HighlightRequest) -> dict[str, Any]:
        """Token spans (``hl-`` classes) for code blocks; ``html`` is empty when no lexer matches."""
        from .highlight import render

        items = await asyncio.to_thread(lambda: [render(item.code, item.lang, item.filename) for item in body.items])
        return {"items": items}

    @router.get("/highlight.css")
    async def highlight_css() -> Response:
        from .highlight import style_css

        return Response(style_css(), media_type="text/css", headers={"Cache-Control": "max-age=3600"})

    return router
