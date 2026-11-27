from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, Field

from pyxis_harness import package_prompts, package_toml

_CFG = package_toml(__file__)
PROMPTS = package_prompts(__file__)

SKILLS_MOUNT = "/skills"

MODES: dict[str, dict[str, str]] = {
    id: {"title": m["title"], "description": m["description"]} for id, m in _CFG["MODES"].items()
}
FALLBACK_MODE = "workspace-write"  # the default mode while `default_mode` names no registered one


@dataclass(frozen=True)
class Mode:
    """Permission mode: the file, shell and approval rules of the built-in mode ``base``, then ``build``."""

    id: str
    title: str
    description: str
    base: str
    build: Callable[[dict[str, Any]], dict[str, Any] | None] | None = None  # on the create_deep_agent kwargs


DEFAULT_SYSTEM_PROMPT: str = PROMPTS["config"]["DEFAULT_SYSTEM_PROMPT"]


class PresetConfig(BaseModel):
    title: str
    description: str = ""
    tools: list[str] | None = Field(None, description="Registered tool names the preset keeps; None keeps all.")
    exclude_tools: list[str] = Field(default_factory=list, description="Registered tool names the preset drops.")
    order: int = 100


DEFAULT_PRESETS: dict[str, PresetConfig] = {id: PresetConfig(**p) for id, p in _CFG["DEFAULT_PRESETS"].items()}


class LoopConfig(BaseModel):
    model: str | None = Field(None, description="Model spec; None selects ctx.llm's default.")
    default_preset: str = Field("standard", description="Agent preset for new sessions.")
    default_mode: str = Field(
        FALLBACK_MODE,
        description="Permission mode for new sessions, built-in or added by a plugin; workspace-write while absent.",
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
    max_parallel_tool_calls: int = Field(10, ge=1, description="Tool calls of one agent running at a time.")
    recursion_limit: int = Field(
        10_000, ge=1, description="LangGraph steps of one run: the bound behind the agents service's max_steps."
    )
