"""Plugin configuration."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class Config(BaseModel):
    shell_tool: bool = True
    shell: str = Field("bash", description="Executable of the persistent shell (bash semantics expected).")
    timeout: int = Field(120, ge=1)
    max_timeout: int = Field(900, ge=1)
    max_output_chars: int = Field(16_000, ge=1000)
    approval: bool | dict[str, Any] = Field(default_factory=lambda: {"allowed_decisions": ["approve", "reject"]})
    jobs_tool: bool = True
    job_tail_lines: int = Field(200, ge=10)
    terminal_tab: bool = True
    terminal_shell: str | None = Field(None, description="Interactive shell for PTY terminals; default $SHELL.")
    scrollback_bytes: int = Field(200_000, ge=10_000)
    max_shells: int = Field(16, ge=1)
