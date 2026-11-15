"""
Antigravity tools: ``antigravity_web_search`` (Gemini with Google Search grounding) and
``antigravity_image_generate`` (Gemini 3.1 Flash Image).
"""

from __future__ import annotations

import base64
import uuid
from typing import Any, Literal, Protocol

from langchain_core.tools import tool
from pydantic import BaseModel, ConfigDict, Field

from pyharness import package_prompts, package_toml

from .common import LlmError, TokenManager
from .media import dedupe_sources, describe_images, format_search, read_reference, save_images
from .store import image_extension


class Client(Protocol):
    """The Antigravity provider, as the tools use it."""

    config: dict[str, Any]

    def token_manager(self, key: str | None = None) -> TokenManager: ...
    async def call(
        self,
        session: dict[str, Any],
        method: str,
        body: dict[str, Any],
        *,
        tolerate_404: bool = False,
        single_origin: bool = False,
        timeout: float = 10.0,
    ) -> dict[str, Any]: ...


_CFG = package_toml(__file__)["antigravity_tools"]
PROMPTS = package_prompts(__file__)["antigravity_tools"]
SEARCH_MODEL: str = _CFG["SEARCH_MODEL"]
IMAGE_MODEL: str = _CFG["IMAGE_MODEL"]


class SearchArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query: str = Field(min_length=1, max_length=16384)


class ImageArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    prompt: str
    referenced_image_paths: list[str] | None = Field(None, description="Local images to use as references.")
    reasoning_effort: Literal["minimal", "high"] | None = None


def make_tools(provider: Client, service: Any) -> list[Any]:
    def request(session: dict[str, Any], model: str, req: dict[str, Any]) -> dict[str, Any]:
        project = (provider.config.get("antigravity") or {}).get("projectId") or session.get("projectId")
        return {
            "project": project,
            "model": model,
            "requestId": str(uuid.uuid4()),
            "userAgent": "antigravity",
            "requestType": "agent",
            "request": {**req, "sessionId": str(uuid.uuid4())},
        }

    @tool(
        "antigravity_web_search",
        description=PROMPTS["antigravity_web_search"],
        args_schema=SearchArgs,
    )
    async def antigravity_web_search(query: str) -> str:
        if not service.tool_enabled("antigravity", "web_search"):
            return "Error: antigravity_web_search is disabled on the AI subscriptions page"
        try:
            session = await provider.token_manager().session()
            data = await provider.call(
                session,
                "generateContent",
                request(
                    session,
                    SEARCH_MODEL,
                    {"contents": [{"role": "user", "parts": [{"text": query}]}], "tools": [{"googleSearch": {}}]},
                ),
                timeout=60,
            )
        except LlmError as exc:
            return f"Error: {exc}"
        response = data.get("response") if isinstance(data.get("response"), dict) else data
        texts: list[str] = []
        raw_sources: list[dict[str, Any]] = []
        for candidate in response.get("candidates") or []:
            texts.extend(
                str(part["text"])
                for part in (candidate.get("content") or {}).get("parts") or []
                if isinstance(part, dict) and part.get("text") and not part.get("thought")
            )
            grounding = candidate.get("groundingMetadata") or candidate.get("grounding_metadata") or {}
            for chunk in grounding.get("groundingChunks") or grounding.get("grounding_chunks") or []:
                web = chunk.get("web") or {}
                raw_sources.append({"url": web.get("uri"), "title": web.get("title")})
        sources = dedupe_sources(raw_sources, limit=8)
        if not sources:
            return PROMPTS["no_sources"]
        content = "\n".join(texts)
        truncated = len(content) > 64 * 1024
        return format_search(content[: 64 * 1024], sources, truncated)

    @tool(
        "antigravity_image_generate",
        description=PROMPTS["antigravity_image_generate"],
        args_schema=ImageArgs,
    )
    async def antigravity_image_generate(
        prompt: str, referenced_image_paths: list[str] | None = None, reasoning_effort: str | None = None
    ) -> str:
        if not service.tool_enabled("antigravity", "image_generate", at_creation=True):
            return "Error: antigravity_image_generate is disabled on the AI subscriptions page"
        parts: list[dict[str, Any]] = [{"text": prompt}]
        for path in referenced_image_paths or []:
            try:
                mime, url = read_reference(path)
            except Exception as exc:  # noqa: BLE001
                return f"Error: cannot read reference image {path}: {exc}"
            parts.append({"inlineData": {"mimeType": mime, "data": url.split(",", 1)[1]}})
        effort = reasoning_effort or service.model_default("antigravity", IMAGE_MODEL) or "minimal"
        req = {
            "contents": [{"role": "user", "parts": parts}],
            "generationConfig": {
                "responseModalities": ["TEXT", "IMAGE"],
                "thinkingConfig": {"thinkingLevel": effort.upper(), "includeThoughts": True},
            },
        }
        try:
            session = await provider.token_manager().session()
            data = await provider.call(session, "generateContent", request(session, IMAGE_MODEL, req), timeout=180)
        except LlmError as exc:
            return f"Error: {exc}"
        response = data.get("response") if isinstance(data.get("response"), dict) else data
        images: list[tuple[bytes, str | None]] = []
        for candidate in response.get("candidates") or []:
            for part in (candidate.get("content") or {}).get("parts") or []:
                inline = part.get("inlineData") if isinstance(part, dict) else None
                if inline and inline.get("data") and not part.get("thought"):
                    raw = base64.b64decode(inline["data"])
                    if (
                        image_extension(raw) in ("png", "jpg", "webp")
                        and len(raw) <= 20 * 1024 * 1024
                        and len(images) < 4
                    ):
                        images.append((raw, None))
        if not images:
            return "Error: Antigravity returned no images"
        paths, _ = save_images(service.media, images)
        return describe_images(paths, None, service.media_url)

    return [antigravity_web_search, antigravity_image_generate]
