from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class Config(BaseModel):
    shell_tool: bool = True
    dialect: Literal["bash", "pwsh"] | None = Field(
        None, description="Shell of the tool; default: PowerShell on Windows, bash elsewhere."
    )
    shell: str = Field("bash", description="bash executable.")
    pwsh: str | None = Field(
        None, description="PowerShell executable; default: PowerShell 7, pwsh on PATH, Windows PowerShell 5.1."
    )
    timeout: int = Field(120, ge=1)
    max_timeout: int = Field(900, ge=1)
    promote_on_timeout: bool = Field(
        True, description="A command that reaches its timeout goes on as a background job (needs jobs_tool)."
    )
    grace: float = Field(3, gt=0, description="Seconds between SIGTERM and SIGKILL when a command is stopped.")
    max_output_chars: int = Field(16_000, ge=1000)
    approval: bool | dict[str, Any] = Field(default_factory=lambda: {"allowed_decisions": ["approve", "reject"]})
    jobs_tool: bool = True
    job_tail_lines: int = Field(200, ge=10)
    terminal_tab: bool = True
    terminal_shell: str | None = Field(None, description="Interactive shell for PTY terminals; default $SHELL.")
    scrollback_bytes: int = Field(200_000, ge=10_000)
