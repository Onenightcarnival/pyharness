"""Plugin configuration."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class Config(BaseModel):
    search: bool = True  # register web_search
    fetch: bool = True  # register web_fetch
    api_key_env: str = "DEEPSEEK_API_KEY"
    base_url: str = "https://api.deepseek.com/anthropic/v1"
    model: str = "deepseek-v4-flash"
    max_uses: int = Field(5, ge=1, le=20)  # searches DeepSeek may run per query
    max_results: int = Field(8, ge=1, le=50)
    max_tokens: int = Field(4096, ge=256)
    search_timeout: float = 90.0
    fetch_timeout: float = 30.0
    fetch_max_chars: int = Field(20_000, ge=1000)
    fetch_max_bytes: int = Field(5_000_000, ge=10_000)
    approval: bool | dict[str, Any] = False
