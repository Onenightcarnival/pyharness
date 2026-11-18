from __future__ import annotations

import asyncio
import json
import uuid
from typing import Any, Literal, Protocol

import httpx
from langchain_core.tools import tool
from pydantic import BaseModel, ConfigDict, Field

from pyharness import package_prompts, package_toml

from .common import LlmError, TokenManager, headers_with_ua, http_error
from .media import dedupe_sources, describe_images, format_search, generate_images, read_reference, save_images


class Client(Protocol):
    """The Codex provider, as the tools use it."""

    http: httpx.AsyncClient

    def token_manager(self, key: str | None = None) -> TokenManager: ...
    def headers(self, session: dict[str, Any], **extra: str) -> dict[str, str]: ...


_CFG = package_toml(__file__)
PROMPTS = package_prompts(__file__)["codex_tools"]
BACKEND: str = _CFG["codex"]["BACKEND"]
SEARCH_MODEL: str = _CFG["codex_tools"]["SEARCH_MODEL"]
IMAGE_MODEL: str = _CFG["codex_tools"]["IMAGE_MODEL"]


class SearchQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")
    q: str
    domains: list[str] | None = None
    recency: int | None = Field(None, description="Only results from the last N days.")


class OpenCmd(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ref_id: str = Field(description="A ref id from an earlier result, or an http(s) URL.")
    lineno: int | None = None


class ClickCmd(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ref_id: str
    id: int = Field(description="Numbered link in the opened page.")


class FindCmd(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ref_id: str
    pattern: str


class ScreenshotCmd(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ref_id: str
    pageno: int = Field(description="Zero-based page number.")


class FinanceCmd(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ticker: str
    type: Literal["equity", "fund", "crypto", "index"]
    market: str | None = Field(None, description="ISO 3166 alpha-3 market, OTC, or empty.")


class WeatherCmd(BaseModel):
    model_config = ConfigDict(extra="forbid")
    location: str
    start: str | None = Field(None, description="YYYY-MM-DD")
    duration: int | None = None


class SportsCmd(BaseModel):
    model_config = ConfigDict(extra="forbid")
    fn: Literal["schedule", "standings"]
    league: Literal["nba", "wnba", "nfl", "nhl", "mlb", "epl", "ncaamb", "ncaawb", "ipl"]
    team: str | None = None
    opponent: str | None = None
    date_from: str | None = None
    date_to: str | None = None
    num_games: int | None = None
    locale: str | None = None


class TimeCmd(BaseModel):
    model_config = ConfigDict(extra="forbid")
    utc_offset: str = Field(description="e.g. +08:00")


class SearchArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    search_query: list[SearchQuery] | None = Field(None, description="Up to 4 web searches.")
    image_query: list[SearchQuery] | None = None
    open: list[OpenCmd] | None = None
    click: list[ClickCmd] | None = None
    find: list[FindCmd] | None = None
    screenshot: list[ScreenshotCmd] | None = None
    finance: list[FinanceCmd] | None = None
    weather: list[WeatherCmd] | None = None
    sports: list[SportsCmd] | None = None
    time: list[TimeCmd] | None = None
    response_length: Literal["short", "medium", "long"] | None = None
    query: str | None = Field(None, description="Shorthand for one search_query.")


class ImageArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    prompt: str
    transparent_background: bool = False
    referenced_image_paths: list[str] | None = Field(
        None, description="1–5 absolute paths of local images to edit or use as references."
    )
    size: Literal["1024x1024", "1024x1536", "1536x1024", "auto"] | None = None
    quality: Literal["low", "medium", "high", "auto"] | None = None


def validate_commands(args: SearchArgs) -> dict[str, Any]:
    commands = {k: v for k, v in args.model_dump(exclude_none=True).items() if k not in ("response_length", "query")}
    if args.query:
        if commands:
            raise ValueError("query cannot be combined with other commands")
        commands = {"search_query": [{"q": args.query}]}
    if not commands:
        raise ValueError("at least one command is required")
    for name, items in commands.items():
        if not items:
            raise ValueError(f"{name} must not be empty")
        for item in items:
            for key, value in item.items():
                if isinstance(value, int) and not isinstance(value, bool) and value < 0:
                    raise ValueError(f"{name}.{key} must be >= 0")
                if isinstance(value, str) and not value.strip() and key != "market":
                    raise ValueError(f"{name}.{key} must not be blank")
    if len(commands.get("search_query", [])) > 4:
        raise ValueError("search_query takes at most 4 entries")
    if len(commands.get("search_query", [])) == 4 and args.response_length not in ("medium", "long"):
        raise ValueError("four search queries need response_length medium or long")
    return commands


def make_tools(provider: Client, service: Any) -> list[Any]:
    @tool(
        "codex_web_search",
        description=PROMPTS["codex_web_search"],
        args_schema=SearchArgs,
    )
    async def codex_web_search(**kwargs: Any) -> str:
        if not service.tool_enabled("codex", "web_search"):
            return "Error: codex_web_search is disabled on the AI subscriptions page"
        args = SearchArgs(**kwargs)
        try:
            commands = validate_commands(args)
        except ValueError as exc:
            return f"Error: {exc}"
        try:
            session = await provider.token_manager().session()
        except LlmError as exc:
            return f"Error: {exc}"
        length = args.response_length or "short"
        body = {
            "id": f"pyxis-harness-subscriptions:{service.current_session_id() or uuid.uuid4()}",
            "model": SEARCH_MODEL,
            "input": "\n".join(q["q"] for q in commands.get("search_query", []))
            or json.dumps(commands, ensure_ascii=False),
            "commands": commands,
            "settings": {"search_context_size": "medium", "allowed_callers": ["direct"], "external_web_access": "live"},
            "max_output_tokens": {"medium": 4096, "long": 8192}.get(length, 2048),
        }
        headers = provider.headers(session, **{"content-type": "application/json"})
        last: Exception | None = None
        for attempt in range(5):
            try:
                res = await provider.http.post(f"{BACKEND}/codex/alpha/search", headers=headers, json=body, timeout=60)
            except httpx.HTTPError as exc:
                last = exc
                await asyncio.sleep(0.1 * 2**attempt)
                continue
            if res.status_code == 429:
                return "Error: Codex search is rate limited; try again later"
            if res.status_code >= 500:
                last = http_error("codex search", res.status_code, res.text)
                await asyncio.sleep(0.1 * 2**attempt)
                continue
            if res.status_code >= 400:
                return f"Error: {http_error('codex search', res.status_code, res.text)}"
            if len(res.content) > 2 * 1024 * 1024:
                return "Error: Codex search response too large"
            data = res.json()
            sources = dedupe_sources(data.get("results") or [])
            return format_search(str(data.get("output") or ""), sources, bool(data.get("truncated")))
        return f"Error: Codex search unavailable: {last}"

    @tool(
        "codex_image_generate",
        description=PROMPTS["codex_image_generate"],
        args_schema=ImageArgs,
    )
    async def codex_image_generate(**kwargs: Any) -> str:
        if not service.tool_enabled("codex", "image_generate", at_creation=True):
            return "Error: codex_image_generate is disabled on the AI subscriptions page"
        args = ImageArgs(**kwargs)
        refs = []
        for path in args.referenced_image_paths or []:
            try:
                refs.append(read_reference(path)[1])
            except Exception as exc:  # noqa: BLE001
                return f"Error: cannot read reference image {path}: {exc}"
        if len(refs) > 5:
            return "Error: at most 5 reference images"
        try:
            session = await provider.token_manager().session()
        except LlmError as exc:
            return f"Error: {exc}"
        body: dict[str, Any] = {
            "prompt": args.prompt,
            "model": IMAGE_MODEL,
            "size": args.size or "auto",
            "quality": args.quality or "auto",
            "background": "transparent" if args.transparent_background else "opaque",
        }
        if refs:
            body["images"] = [{"image_url": r} for r in refs]
        url = f"{BACKEND}/codex/images/{'edits' if refs else 'generations'}"
        headers = {
            k: v
            for k, v in headers_with_ua(
                provider.headers(session, **{"content-type": "application/json", "accept": "application/json"})
            ).items()
            if k != "user-agent"
        }
        try:
            images = await generate_images(provider.http, url, headers, body, "codex images")
        except LlmError as exc:
            return f"Error: {exc}"
        paths, revised = save_images(service.media, images)
        return describe_images(paths, revised, service.media_url)

    return [codex_web_search, codex_image_generate]
