"""Permission modes, agent presets and the loop configuration.

| name                      | contract                                                                  |
|---------------------------|---------------------------------------------------------------------------|
| ``SKILLS_MOUNT``          | root of the read-only skills mounts: ``/skills/<label>/``                 |
| ``MODES``                 | permission modes by id: ``title``, ``description``                        |
| ``DEFAULT_SYSTEM_PROMPT`` | identity section of the system prompt (order 0)                           |
| ``PresetConfig``          | one agent preset: title, description, kept / dropped tools, order         |
| ``DEFAULT_PRESETS``       | ``standard`` and ``creator``                                              |
| ``LoopConfig``            | the service configuration                                                 |
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from pyharness import package_prompts, package_toml

_CFG = package_toml(__file__)
PROMPTS = package_prompts(__file__)

SKILLS_MOUNT = "/skills"

MODES: dict[str, dict[str, str]] = {
    id: {"title": m["title"], "description": m["description"]} for id, m in _CFG["modes"].items()
}

DEFAULT_SYSTEM_PROMPT: str = PROMPTS["config"]["default_system_prompt"]


class PresetConfig(BaseModel):
    title: str
    description: str = ""
    tools: list[str] | None = Field(None, description="Registered tool names the preset keeps; None keeps all.")
    exclude_tools: list[str] = Field(default_factory=list, description="Registered tool names the preset drops.")
    order: int = 100


DEFAULT_PRESETS: dict[str, PresetConfig] = {id: PresetConfig(**p) for id, p in _CFG["presets"].items()}


class LoopConfig(BaseModel):
    model: str | None = Field(None, description="Model spec; None selects ctx.llm's default.")
    default_preset: str = Field("standard", description="Agent preset for new sessions.")
    default_mode: str = Field(
        "workspace-write", description="Permission mode for new sessions: read-only, workspace-write, full-access."
    )
    presets: dict[str, PresetConfig] = Field(
        default_factory=lambda: dict(DEFAULT_PRESETS), description="Agent presets by id."
    )
    system_prompt: str = Field(DEFAULT_SYSTEM_PROMPT, description="Identity section of the system prompt (order 0).")
    interrupt_on: dict[str, Any] = Field(default_factory=dict, description="Additional approval gates by tool name.")
    subagents: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Declarative deepagents SubAgent specs; `tools` entries are registered tool names or tools.",
    )
    skills: list[str] | None = Field(
        None, description="Skill source paths in the backend (workspace paths such as /skills/mine/)."
    )
    memory: list[str] | None = Field(None, description="AGENTS.md-style memory files, relative to the backend root.")
    recursion_limit: int = 200
