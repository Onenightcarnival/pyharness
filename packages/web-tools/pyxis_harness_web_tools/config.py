from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class Config(BaseModel):
    agent_tools: bool = Field(
        True, description="The agent has the tools; the value until the switch of the settings section is set."
    )
    search: bool = True  # web_search exists
    fetch: bool = True  # web_fetch exists
    api_key_env: str = "DEEPSEEK_API_KEY"
    search_provider: Literal["deepseek-search-api", "deepseek-legacy"] = Field(
        "deepseek-search-api",
        description="deepseek-search-api: one direct Search API request; deepseek-legacy: a Messages call with the "
        "web_search server tool.",
    )
    search_base_url: str = Field(
        "https://api.deepseek.com/v1/tools", description="Search API base; /search is appended."
    )
    search_requests_per_second: int = Field(5, ge=1, description="Search API requests started per second.")
    summary_max_chars: int = Field(800, ge=100, description="Cap of one source summary in the tool result.")
    max_results: int = Field(10, ge=1, le=50)
    # deepseek-legacy
    base_url: str = "https://api.deepseek.com/anthropic/v1"
    model: str = "deepseek-v4-flash"
    max_uses: int = Field(5, ge=1, le=20)  # searches DeepSeek may run per query
    max_tokens: int = Field(4096, ge=256)
    search_timeout: float = 90.0
    fetch_timeout: float = 30.0
    fetch_max_chars: int = Field(20_000, ge=1000)
    fetch_max_bytes: int = Field(5_000_000, ge=10_000)
    approval: bool | dict[str, Any] = False
