from __future__ import annotations

import os
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import PureWindowsPath

# Per dialect: what keeps colours and pagers out of the output.
ENVIRONMENT: dict[str, dict[str, str]] = {
    "bash": {"NO_COLOR": "1", "TERM": "dumb", "PAGER": "cat", "GIT_PAGER": "cat"},
    "pwsh": {"NO_COLOR": "1", "PAGER": "cat", "GIT_PAGER": "cat"},
}
# Windows PowerShell 5.1 writes the console code page; the output is read as UTF-8.
PWSH_UTF8 = (
    "[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false); "
    "$OutputEncoding = [System.Text.UTF8Encoding]::new($false); "
)
PWSH_FLAGS = ["-NoLogo", "-NoProfile", "-NonInteractive", "-Command"]


@dataclass(frozen=True)
class Shell:
    """The shell a command runs in: a fresh process per command."""

    dialect: str  # "bash" | "pwsh"; also the name of the tool
    executable: str

    def argv(self, command: str) -> list[str]:
        if self.dialect == "pwsh":
            return [self.executable, *PWSH_FLAGS, PWSH_UTF8 + command]
        return [self.executable, "-c", command]

    def environment(self, base: Mapping[str, str] | None = None) -> dict[str, str]:
        return {**(os.environ if base is None else base), **ENVIRONMENT[self.dialect]}


def pwsh_candidates(env: Mapping[str, str]) -> list[str]:
    """PowerShell executables on Windows, best first: PowerShell 7, ``pwsh.exe`` on PATH, Windows PowerShell 5.1."""
    program_files = env.get("ProgramFiles") or "C:\\Program Files"
    system_root = env.get("SystemRoot") or "C:\\Windows"
    on_path = [entry.strip().strip('"') for entry in (env.get("PATH") or "").split(";")]
    return [
        str(PureWindowsPath(program_files, "PowerShell", "7", "pwsh.exe")),
        *(str(PureWindowsPath(entry, "pwsh.exe")) for entry in on_path if entry),
        str(PureWindowsPath(system_root, "System32", "WindowsPowerShell", "v1.0", "powershell.exe")),
    ]


def resolve_pwsh(
    configured: str | None = None,
    env: Mapping[str, str] | None = None,
    platform: str = sys.platform,
    exists: Callable[[str], bool] = os.path.isfile,
) -> str:
    """The PowerShell executable: the configured one, else the first candidate that exists, else ``pwsh`` on PATH."""
    if configured:
        return configured
    if platform == "win32":
        for candidate in pwsh_candidates(os.environ if env is None else env):
            if exists(candidate):
                return candidate
    return "pwsh"


def shell_of(dialect: str | None, bash: str, pwsh: str | None, platform: str = sys.platform) -> Shell:
    """The shell of this host: PowerShell on Windows, bash elsewhere; ``dialect`` overrides the choice."""
    chosen = dialect or ("pwsh" if platform == "win32" else "bash")
    return Shell(chosen, resolve_pwsh(pwsh, platform=platform) if chosen == "pwsh" else bash)


def decode(data: bytes) -> str:
    """Output bytes as text with ``\\n`` line ends: UTF-8; on Windows, other bytes are read in the OEM code page."""
    try:
        text = data.decode()
    except UnicodeDecodeError:
        text = data.decode("oem" if sys.platform == "win32" else "utf-8", errors="replace")
    return text.replace("\r\n", "\n")


def tail(text: str, limit: int) -> tuple[str, bool]:
    """The last ``limit`` characters of ``text``, from a line start where one is near; and whether text was cut."""
    if len(text) <= limit:
        return text, False
    kept = text[-limit:]
    newline = kept.find("\n")
    return (kept[newline + 1 :] if 0 <= newline < limit // 4 else kept), True
