from __future__ import annotations

import inspect
import json
from collections.abc import Callable
from pathlib import Path
from textwrap import dedent
from typing import Any, ClassVar

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel

from pyharness import Service

INDEX = Path(__file__).with_name("index.html")
VENDOR = Path(__file__).with_name("vendor")
VENDOR_FILES: dict[str, str] = {"katex.min.js": "application/javascript"}  # file name -> content type
PREF_IDS = 200  # ids in ``unpinnedPanels``
PREF_ID_CHARS = 200  # characters of one id

# Extension slots the page declares; mirrored for ``harness_inspect`` and the plugin-authoring skill.
SLOTS: list[dict[str, Any]] = [
    {
        "name": "sidebar.panellist",
        "kind": "list",
        "entry": dedent(
            """
            {id, label, icon?, description?, order?}; selecting it opens the `main` panel with the same key;
            the user unpins an entry from its row and pins it back from the More menu, which lists unpinned entries
            """
        ).strip(),
        "props": {},
    },
    {
        "name": "sidebar.more",
        "kind": "list",
        "entry": "{id, label, icon?, order?, onPick()}; a row of the sidebar More menu",
        "props": {},
    },
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
    {
        "name": "settings.sections",
        "kind": "keyed",
        "entry": "{key, label, icon?, order?} + mount(el, props); a Settings tab",
        "props": {},
    },
    {
        "name": "rightbar.tabs",
        "kind": "keyed",
        "entry": dedent(
            """
            a right-sidebar tab type: {key, label, icon?, guide?: {title, description?, order?}, multiple?,
            contentId?(params), title?(params)} + mount(el, props);
            `guide` (the start page), `files`, `preview` and `info` are built in;
            a type with `guide` gets a card on the start page
            """
        ).strip(),
        "props": {
            "session": "current session record or null",
            "workspace": "workspace root of the session",
            "tab": dedent(
                """
                {id, kind, params, title, store, setTitle(t), close(), openTab(kind, {params, replaceTab}),
                openFile(path), replaceWith(kind, opts)}
                """
            ).strip(),
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
        return {
            "entry": self.entry,
            "path": str(self.path),
            "rev": self.rev,
            "calls": sorted(self.calls),
            "inject": list(self.inject),
        }


def unpinned_panels(value: Any) -> list[str]:
    """``value`` as a list of panel ids without repeats; ``ValueError`` when it is not one."""
    if not isinstance(value, list) or len(value) > PREF_IDS:
        raise ValueError(f"unpinnedPanels is a list of at most {PREF_IDS} strings")
    if not all(isinstance(item, str) and len(item) <= PREF_ID_CHARS for item in value):
        raise ValueError(f"unpinnedPanels holds strings of at most {PREF_ID_CHARS} characters")
    return list(dict.fromkeys(value))


class PrefsStore:
    """Page preferences as one JSON object at ``path``, written atomically; in memory when ``path`` is ``None``."""

    def __init__(self, path: Path | None) -> None:
        self.path = path
        self._memory: dict[str, Any] = {}

    def read(self) -> dict[str, Any]:
        """The stored preferences; a missing or unreadable file or value reads as the default."""
        stored: Any = self._memory
        if self.path is not None:
            try:
                stored = json.loads(self.path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                stored = {}
        try:
            unpinned = unpinned_panels(stored.get("unpinnedPanels", []) if isinstance(stored, dict) else [])
        except ValueError:
            unpinned = []
        return {"unpinnedPanels": unpinned}

    def write(self, prefs: Any) -> dict[str, Any]:
        """Store ``prefs`` and return the stored object; ``ValueError`` when ``prefs`` is not a preferences object."""
        if not isinstance(prefs, dict) or set(prefs) != {"unpinnedPanels"}:
            raise ValueError('preferences are an object {"unpinnedPanels": [ids]}')
        stored = {"unpinnedPanels": unpinned_panels(prefs["unpinnedPanels"])}
        if self.path is None:
            self._memory = stored
            return stored
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(self.path.name + ".tmp")
        tmp.write_text(json.dumps(stored, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        tmp.replace(self.path)
        return stored


class WebUIService(Service):
    """The Web UI page and the client-module registry."""

    key = "webui"
    name = "pyharness-web-ui"
    inject: ClassVar[list[str]] = ["http"]
    Config = Config

    def __init__(self, ctx: Any, config: Config) -> None:
        super().__init__(ctx, config)
        self._clients: dict[str, ClientModule] = {}
        self._html = INDEX.read_text(encoding="utf-8")
        self.prefs = PrefsStore(None)

    async def start(self) -> None:
        profile = self.ctx.get("profile", None)
        if profile is not None and hasattr(profile, "data"):
            self.prefs = PrefsStore(Path(profile.data) / "web-ui" / "prefs.json")
        self.ctx.http.include_router(self._router(), include_in_schema=False)

    # ------------------------------------------------------------------ registry
    def register_client(
        self, path: str | Path, *, calls: dict[str, Callable[..., Any]] | None = None, inject: list[str] | None = None
    ) -> Callable[[], Any]:
        """
        Serve ``path`` as the calling plugin's browser module; ``calls`` answer ``ctx.host.call``.

        Returns the disposer.
        """
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
                {
                    "id": c.entry,
                    "url": f"{prefix}/{c.entry}/client.js?rev={c.rev}",
                    "inject": c.inject,
                    "calls": sorted(c.calls),
                }
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
            except ValueError:
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

        @router.get("/vendor/{name}")
        async def vendor(name: str) -> Response:
            media = VENDOR_FILES.get(name)
            if media is None:
                raise HTTPException(404, f"no vendored file {name!r}")
            try:
                body = (VENDOR / name).read_bytes()
            except OSError as exc:
                raise HTTPException(404, str(exc)) from None
            headers = {"Cache-Control": "public, max-age=31536000, immutable"}
            return Response(body, media_type=media, headers=headers)

        @router.get("/api/webui/prefs")
        async def read_prefs() -> dict[str, Any]:
            return self.prefs.read()

        @router.put("/api/webui/prefs")
        async def write_prefs(request: Request) -> dict[str, Any]:
            try:
                return self.prefs.write(await request.json())
            except ValueError as exc:
                raise HTTPException(400, str(exc)) from None
            except OSError as exc:
                raise HTTPException(500, f"preferences not saved: {exc}") from None

        return router
