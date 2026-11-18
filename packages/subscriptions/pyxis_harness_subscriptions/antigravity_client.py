from __future__ import annotations

import asyncio
import platform
import re
import sys

import httpx

from pyxis_harness import package_toml

_CFG = package_toml(__file__)["antigravity_client"]
CLI_VERSION_FALLBACK: str = _CFG["CLI_VERSION_FALLBACK"]
CLI_CHANGE_LIST: str = _CFG["CLI_CHANGE_LIST"]
CLI_VERSION_URL: str = _CFG["CLI_VERSION_URL"]
VERSION_FETCH_TIMEOUT_S: float = _CFG["VERSION_FETCH_TIMEOUT_S"]
ARCH_NAMES: dict[str, str] = dict(_CFG["ARCH_NAMES"])
SEMVER = re.compile(r"\d+\.\d+\.\d+")


def parse_cli_version(text: str) -> str | None:
    match = SEMVER.search(text)
    return match.group(0) if match else None


def build_user_agent(version: str, system: str | None = None, machine: str | None = None) -> str:
    """The CLI signature for ``version`` on ``system`` (``sys.platform``) and ``machine`` (``platform.machine()``)."""
    os_type = (system or sys.platform).replace("win32", "windows")
    arch = (machine or platform.machine()).lower()
    arch = ARCH_NAMES.get(arch, arch)
    client = f"aidev_client; os_type={os_type}; arch={arch}; cl={CLI_CHANGE_LIST}; auth_method=consumer"
    return f"antigravity/cli/{version} ({client})"


class CliVersion:
    """The CLI version of one provider instance."""

    def __init__(self) -> None:
        self.current = CLI_VERSION_FALLBACK
        self._primed: asyncio.Task[str] | None = None

    async def _read(self, http: httpx.AsyncClient) -> str:
        try:
            response = await http.get(CLI_VERSION_URL, timeout=VERSION_FETCH_TIMEOUT_S)
        except httpx.HTTPError:
            return self.current
        if response.is_success:
            self.current = parse_cli_version(response.text[:4096]) or self.current
        return self.current

    async def prime(self, http: httpx.AsyncClient) -> str:
        """Read the stable CLI version once; concurrent and later callers share that request."""
        if self._primed is None:
            self._primed = asyncio.ensure_future(self._read(http))
        return await asyncio.shield(self._primed)
