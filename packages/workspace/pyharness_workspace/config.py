from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class Config(BaseModel):
    root: str | None = Field(
        None, description="Default agent working directory; unset: the profile's directory under the user's Documents."
    )
    virtual_mode: bool = True
    shell: bool = Field(False, description="`execute` tool on a local, unsandboxed shell.")
    shell_approval: bool = True
    shell_timeout: int = 120
    recent_limit: int = Field(20, description="Workspaces remembered for the picker.")
    picker: Literal["auto", "native", "browse"] = Field(
        "auto", description="Directory picker: the OS dialog when available, else the in-app browser."
    )
    picker_command: list[str] | None = Field(
        None,
        description="Command printing the chosen directory (empty output: cancelled); replaces the platform dialog.",
    )
    picker_timeout: int = Field(600, description="Seconds to wait for the OS dialog.")
