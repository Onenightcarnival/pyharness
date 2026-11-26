from __future__ import annotations

from .config import Config
from .jobs import Job, JobRegistry
from .process import Tree, spawn
from .pty import Terminal, pty_available
from .service import TerminalService
from .shell import Shell, decode, pwsh_candidates, resolve_pwsh, shell_of, tail

__all__ = [
    "Config",
    "Job",
    "JobRegistry",
    "Shell",
    "Terminal",
    "TerminalService",
    "Tree",
    "decode",
    "pty_available",
    "pwsh_candidates",
    "resolve_pwsh",
    "shell_of",
    "spawn",
    "tail",
]
