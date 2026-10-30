"""``ctx.webui``: the Web UI page at ``config.path`` on ``ctx.http``, plus the client-module registry for plugins.

| member                                   | contract                                                                 |
|------------------------------------------|--------------------------------------------------------------------------|
| ``register_client(path, calls=, inject=)`` | serve ``path`` (a browser module) for the calling plugin; ``calls`` answer ``ctx.host.call`` from the page |
| ``clients()``                            | registered client modules: entry id, revision, calls                     |
| ``slots()``                              | the page's extension slots with their kinds and props (:data:`SLOTS`)    |

| route                              | content                                                                 |
|------------------------------------|-------------------------------------------------------------------------|
| ``GET /``                          | the page; ``window.__PYH_BOOT__`` carries the client-module manifest    |
| ``GET /plugins/boot.json``         | the same manifest, fetched by a page that was served without it         |
| ``GET /plugins/{entry}/client.js`` | the plugin's browser module (``?rev=`` of its mtime and size)           |
| ``POST /plugins/{entry}/call/{m}`` | JSON body → ``calls[m](args)`` → ``{"result": ...}``                    |

Browser module contract (plain JavaScript, no bundler)::

    window.__PyhModules__.load({
      id: "<entry id>",  // the patch entry's id; a file registering one module is accepted under its entry id
      factory(require) {
        const { h, icon, esc, toast } = require("pyharness");
        return { apply(ctx) { ctx.slots.register({ slot: "main", key: "my-panel", label: "My panel", icon: "box" }, (el, props) => { el.textContent = "hi"; return () => {}; }); } };
      },
    });

``ctx`` in the page: ``slots.register(spec, mount?)``, ``api(path, init)``, ``host.call(method, args)``, ``on(event, fn)``
(``session``, ``run``, ``health``), ``effect(cleanup)``, ``locale``, ``theme()``, ``rightbar.openTab(kind, {params})`` /
``rightbar.openFile(path)`` / ``rightbar.close(tabId)`` / ``rightbar.isExpanded()`` / ``rightbar.toggle()``.
"""

from __future__ import annotations

import inspect
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel

from pyharness import Service

INDEX = Path(__file__).with_name("index.html")

# Extension slots the page declares; mirrored for ``harness_inspect`` and the plugin-authoring skill.
SLOTS: list[dict[str, Any]] = [
    {
        "name": "sidebar.panellist",
        "kind": "list",
        "entry": "{id, label, icon?, order?}; selecting it opens the `main` panel with the same key",
        "props": {},
    },
    {"name": "sidebar.more", "kind": "list", "entry": "{id, label, icon?, order?, onPick()}; a row of the sidebar More menu", "props": {}},
    {
        "name": "main",
        "kind": "keyed",
        "entry": "{key, label?} + mount(el, props); a global panel; `conversation` and `plugins` are built in",
        "props": {"session": "current session record or null"},
    },
    {
        "name": "conversation.composer.dock",
        "kind": "list",
        "entry": "{id, order?} + mount(el, props); inline beside the composer controls",
        "props": {"session": "current session record or null"},
    },
    {"name": "settings.sections", "kind": "keyed", "entry": "{key, label, icon?, order?} + mount(el, props); a Settings tab", "props": {}},
    {
        "name": "rightbar.tabs",
        "kind": "keyed",
        "entry": "a right-sidebar tab type: {key, label, icon?, guide?: {title, description?, order?}, multiple?, contentId?(params), title?(params)} + mount(el, props); "
        "`guide` (the start page), `files`, `preview` and `info` are built in; a type with `guide` gets a card on the start page",
        "props": {
            "session": "current session record or null",
            "workspace": "workspace root of the session",
            "tab": "{id, kind, params, title, store, setTitle(t), close(), openTab(kind, {params, replaceTab}), openFile(path), replaceWith(kind, opts)}",
        },
    },
]


class Config(BaseModel):
    path: str = "/"
    plugins_prefix: str = "/plugins"


class ClientModule:
    def __init__(self, entry: str, path: Path, calls: dict[str, Callable[..., Any]], inject: list[str]) -> None:
        self.entry = entry
        self.path = path
        self.calls = calls
        self.inject = inject

    @property
    def rev(self) -> str:
        try:
            stat = self.path.stat()
        except OSError:
            return "0"
        return f"{int(stat.st_mtime)}-{stat.st_size}"

    def describe(self) -> dict[str, Any]:
        return {"entry": self.entry, "path": str(self.path), "rev": self.rev, "calls": sorted(self.calls), "inject": list(self.inject)}


class WebUIService(Service):
    """The Web UI page and the client-module registry."""

    key = "webui"
    name = "pyharness-web-ui"
    inject = ["http"]
    Config = Config

    def __init__(self, ctx: Any, config: Config) -> None:
        super().__init__(ctx, config)
        self._clients: dict[str, ClientModule] = {}
        self._html = INDEX.read_text(encoding="utf-8")

    async def start(self) -> None:
        self.ctx.http.include_router(self._router(), include_in_schema=False)

    # ------------------------------------------------------------------ registry
    def register_client(
        self, path: str | Path, *, calls: dict[str, Callable[..., Any]] | None = None, inject: list[str] | None = None
    ) -> Callable[[], Any]:
        """Serve ``path`` as the calling plugin's browser module; ``calls`` answer ``ctx.host.call``. Returns the disposer."""
        entry = self.caller.entry_id
        file = Path(path).expanduser().resolve()
        if not file.is_file():
            raise ValueError(f"client module {file} does not exist")
        if entry in self._clients:
            raise ValueError(f"entry {entry!r} already registered a client module")
        self._clients[entry] = ClientModule(entry, file, dict(calls or {}), list(inject or []))
        return self.caller.on_dispose(lambda: self._clients.pop(entry, None))

    def clients(self) -> list[dict[str, Any]]:
        return [c.describe() for c in self._clients.values()]

    def slots(self) -> list[dict[str, Any]]:
        return [dict(s) for s in SLOTS]

    def boot_manifest(self) -> dict[str, Any]:
        prefix = self.config.plugins_prefix
        return {
            "plugins": [
                {"id": c.entry, "url": f"{prefix}/{c.entry}/client.js?rev={c.rev}", "inject": c.inject, "calls": sorted(c.calls)}
                for c in self._clients.values()
            ],
            "generation": self.ctx.lifecycle.generation,
        }

    # ------------------------------------------------------------------ routes
    def _router(self) -> APIRouter:
        router = APIRouter()
        prefix = self.config.plugins_prefix

        @router.get(self.config.path, response_class=HTMLResponse)
        async def index() -> str:
            boot = json.dumps(self.boot_manifest(), ensure_ascii=False).replace("<", "\\u003c")
            return self._html.replace("</head>", f"<script>window.__PYH_BOOT__ = {boot};</script>\n</head>", 1)

        @router.get(prefix + "/boot.json")
        async def boot_json() -> dict[str, Any]:
            # For pages served by another plugin (a patched copy of the UI) that lack the inline manifest.
            return self.boot_manifest()

        @router.get(prefix + "/{entry}/client.js")
        async def client_js(entry: str) -> Response:
            client = self._clients.get(entry)
            if client is None:
                raise HTTPException(404, f"no client module for entry {entry!r}")
            try:
                body = client.path.read_text(encoding="utf-8")
            except OSError as exc:
                raise HTTPException(404, str(exc)) from None
            return Response(body, media_type="application/javascript", headers={"Cache-Control": "no-cache"})

        @router.post(prefix + "/{entry}/call/{method}")
        async def call(entry: str, method: str, request: Request) -> dict[str, Any]:
            client = self._clients.get(entry)
            if client is None or method not in client.calls:
                raise HTTPException(404, f"no call {method!r} on entry {entry!r}")
            try:
                args = await request.json()
            except Exception:
                args = {}
            if not isinstance(args, dict):
                raise HTTPException(422, "call arguments must be a JSON object")
            fn = client.calls[method]
            try:
                result = fn(args)
                if inspect.isawaitable(result):
                    result = await result
            except ValueError as exc:
                raise HTTPException(422, str(exc)) from None
            return {"result": result}

        return router


__all__ = ["INDEX", "SLOTS", "ClientModule", "Config", "WebUIService"]
