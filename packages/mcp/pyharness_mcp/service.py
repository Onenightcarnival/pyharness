from __future__ import annotations

import asyncio
import os
import re
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any, ClassVar

from langchain_mcp_adapters.client import MultiServerMCPClient

from pyharness import Service

from .config import Config, ServerConfig
from .templates import expand, has_template, redact, references


def slug(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_]+", "_", name).strip("_") or "server"


def managed_bun(data_dir: str | os.PathLike[str] | None) -> tuple[Path, dict[str, str]] | None:
    """
    The bun runtime installed by the configuration center (``<profile data>/toolkit/bun/bin/bun``) and its
    environment, or ``None`` when it is not installed.
    """
    if data_dir is None:
        return None
    root = Path(data_dir) / "toolkit" / "bun"
    exe = root / "bin" / ("bun.exe" if sys.platform == "win32" else "bun")
    if not exe.exists():
        return None
    return exe, {"BUN_INSTALL": str(root), "BUN_INSTALL_CACHE_DIR": str(root / "cache"), "NO_UPDATE_NOTIFIER": "1"}


def connection_of(cfg: ServerConfig, data_dir: str | os.PathLike[str] | None = None) -> dict[str, Any]:
    """
    The ``langchain-mcp-adapters`` connection for a server configuration. A bare ``bun`` / ``bunx`` command runs
    through the managed bun under ``data_dir`` when that runtime is installed.
    """
    if cfg.command:
        command, env = cfg.command, dict(cfg.env)
        bun = managed_bun(data_dir) if command.lower() in ("bun", "bunx", "bun.exe", "bunx.exe") else None
        if bun is not None:
            exe, bun_env = bun
            command = (
                str(exe.with_name(exe.name.replace("bun", "bunx", 1)))
                if command.lower().startswith("bunx")
                else str(exe)
            )
            env = {**bun_env, **env}
        conn: dict[str, Any] = {"transport": "stdio", "command": command, "args": list(cfg.args)}
        if env:
            conn["env"] = env
        if cfg.cwd:
            conn["cwd"] = cfg.cwd
        return conn
    if not cfg.url:
        raise ValueError("a server needs `command` (stdio) or `url` (streamable_http / sse)")
    conn = {"transport": cfg.transport or "streamable_http", "url": cfg.url}
    if cfg.headers:
        conn["headers"] = dict(cfg.headers)
    return conn


MASK = "••••"


class MCPService(Service):
    """MCP servers as tools."""

    key = "mcp"
    name = "pyharness-mcp"
    inject: ClassVar[list[str]] = ["tools"]
    Config = Config

    def __init__(self, ctx: Any, config: Config) -> None:
        super().__init__(ctx, config)
        self._status: dict[str, dict[str, Any]] = {}

    async def start(self) -> None:
        for name, cfg in self.config.servers.items():
            if not cfg.enabled:
                self._status[name] = {"state": "disabled", "tools": []}
                continue
            expanded, values, missing = expand(cfg, self._lookup())
            if missing:
                self._status[name] = {"state": "waiting-credentials", "missing": missing, "tools": []}
                self.ctx.logger.warning("mcp server %s waits for credentials: %s", name, ", ".join(missing))
                continue
            try:
                tools = await asyncio.wait_for(self._load(name, expanded), self.config.connect_timeout)
            except Exception as exc:  # noqa: BLE001 - one server must not stop the boot
                error = redact(f"{type(exc).__name__}: {exc}", values)
                self._status[name] = {"state": "error", "error": error[:500], "tools": []}
                self.ctx.logger.warning("mcp server %s unavailable: %s", name, error)
                continue
            registered: list[str] = []
            for tool in tools:
                if cfg.prefix:
                    tool.name = f"{slug(name)}_{tool.name}"
                try:
                    self.ctx.tools.register(tool, approval=cfg.approval, tags=("mcp", name))
                    registered.append(tool.name)
                except Exception as exc:  # noqa: BLE001 - name clash with another plugin's tool
                    self.ctx.logger.warning(
                        "mcp tool %s of %s not registered: %s", tool.name, name, redact(str(exc), values)
                    )
            self._status[name] = {"state": "connected", "tools": registered}

    async def _load(self, name: str, cfg: ServerConfig) -> list[Any]:
        client = MultiServerMCPClient({name: connection_of(cfg, self.data_dir())})
        return list(await client.get_tools())

    def data_dir(self) -> Path | None:
        profile = self.ctx.get("profile", None)
        return Path(profile.data) if profile is not None and hasattr(profile, "data") else None

    def _lookup(self) -> Callable[[str], str | None]:
        """Value of a credential reference: the profile credential store; without a profile, the environment."""
        profile = self.ctx.get("profile", None)
        if profile is not None and hasattr(profile, "credentials"):
            return profile.credentials.get
        return lambda reference: os.environ.get(reference) or None

    def _describe(self, reference: str) -> dict[str, Any]:
        """``reference``, ``configured`` and ``source`` (``env``, ``store`` or ``None``) of a credential reference."""
        profile = self.ctx.get("profile", None)
        if profile is not None and hasattr(profile, "credentials"):
            return profile.credentials.describe(reference)
        configured = bool(os.environ.get(reference))
        return {"reference": reference, "configured": configured, "source": "env" if configured else None}

    async def probe(self, cfg: ServerConfig, timeout: float | None = None) -> dict[str, Any]:
        """
        Connect to a server configuration without registering anything: ``{"ok", "tools": [names]}``.

        | failure               | ``ok`` is ``False``, with                                                      |
        |-----------------------|--------------------------------------------------------------------------------|
        | unresolved credential | ``"code": "waiting-credentials"``, ``"error": "missing credentials: A, B"``    |
        | no handshake in time  | ``"code": "timeout"``, ``error``                                               |
        | any other             | ``"code": "error"``, ``error``                                                 |
        """
        expanded, values, missing = expand(cfg, self._lookup())
        if missing:
            return {"ok": False, "code": "waiting-credentials", "error": f"missing credentials: {', '.join(missing)}"}
        try:
            tools = await asyncio.wait_for(self._load("probe", expanded), timeout or self.config.connect_timeout)
            return {"ok": True, "tools": [t.name for t in tools]}
        except TimeoutError:
            return {
                "ok": False,
                "code": "timeout",
                "error": f"no MCP handshake within {timeout or self.config.connect_timeout:g} s",
            }
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "code": "error", "error": redact(f"{type(exc).__name__}: {exc}", values)[:600]}

    # ------------------------------------------------------------------ views
    def status(self) -> dict[str, dict[str, Any]]:
        """
        Per server: ``state`` (connected / error / disabled / waiting-credentials), ``tools`` (registered names),
        ``error``, ``missing`` (unresolved credential references).
        """
        return {name: dict(value) for name, value in self._status.items()}

    def servers(self) -> dict[str, dict[str, Any]]:
        """
        Configured servers with their status.

        | field                     | value                                                                      |
        |---------------------------|----------------------------------------------------------------------------|
        | ``env``, ``headers``      | a value with a credential template as written; any other value :data:`MASK` |
        | ``credentials``           | ``{reference, configured, source}`` per referenced credential, no value    |
        """
        out = {}
        for name, cfg in self.config.servers.items():
            data = cfg.model_dump()
            data["env"] = {key: value if has_template(value) else MASK for key, value in cfg.env.items()}
            data["headers"] = {key: value if has_template(value) else MASK for key, value in cfg.headers.items()}
            data["credentials"] = [self._describe(reference) for reference in references(cfg)]
            out[name] = {
                **data,
                **self._status.get(name, {"state": "disabled" if not cfg.enabled else "unknown", "tools": []}),
            }
        return out
