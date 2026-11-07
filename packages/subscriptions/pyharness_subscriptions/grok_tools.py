"""Grok tools: ``grok_x_search`` (hosted X search), ``grok_image_generate`` and ``grok_video_generate``."""

from __future__ import annotations

import asyncio
import time
from textwrap import dedent
from typing import TYPE_CHECKING, Any, Literal
from urllib.parse import quote

import httpx
from langchain_core.tools import tool
from pydantic import BaseModel, ConfigDict, Field

from pyharness import package_toml

from .common import LlmError, http_error
from .media import describe_images, generate_images, read_reference, save_images

if TYPE_CHECKING:
    from .grok import GrokProvider

_CFG = package_toml(__file__)
API: str = _CFG["grok"]["API"]
SEARCH_MODEL: str = _CFG["grok_tools"]["SEARCH_MODEL"]
IMAGE_MODEL: str = _CFG["grok_tools"]["IMAGE_MODEL"]
VIDEO_MODEL: str = _CFG["grok_tools"]["VIDEO_MODEL"]
ASPECT: dict[str, str] = dict(_CFG["grok_tools"]["ASPECT"])


class XSearchArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query: str
    allowed_x_handles: list[str] | None = None
    excluded_x_handles: list[str] | None = None
    from_date: str | None = Field(None, description="YYYY-MM-DD")
    to_date: str | None = Field(None, description="YYYY-MM-DD")
    enable_image_understanding: bool | None = None
    enable_video_understanding: bool | None = None


class ImageArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    prompt: str
    referenced_image_paths: list[str] | None = None
    size: Literal["1024x1024", "1024x1536", "1536x1024", "auto"] | None = None
    quality: Literal["low", "medium", "high", "auto"] | None = None


class VideoArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    prompt: str
    duration: int | None = Field(None, ge=1, le=15, description="Seconds, 1–15.")
    aspect_ratio: Literal["16:9", "9:16", "1:1", "4:3", "3:4", "3:2", "2:3"] | None = None
    resolution: Literal["480p", "720p", "1080p"] | None = None
    image_url: str | None = Field(None, description="Public URL or data URL of a still image (image-to-video).")


def make_tools(provider: GrokProvider, service: Any) -> list[Any]:
    @tool(
        "grok_x_search",
        description=dedent(
            """
            Search X (Twitter) posts, profiles and threads through the Grok subscription;
            returns an answer with citation URLs.
            """
        ).strip(),
        args_schema=XSearchArgs,
    )
    async def grok_x_search(**kwargs: Any) -> str:
        if not service.tool_enabled("grok", "x_search"):
            return "Error: grok_x_search is disabled on the AI subscriptions page"
        args = XSearchArgs(**kwargs)
        allowed = [h.strip().lstrip("@") for h in args.allowed_x_handles or [] if h.strip()]
        excluded = [h.strip().lstrip("@") for h in args.excluded_x_handles or [] if h.strip()]
        if allowed and excluded:
            return "Error: allowed_x_handles and excluded_x_handles cannot both be used"
        if len(allowed) > 10 or len(excluded) > 10:
            return "Error: at most 10 handles"
        tool_spec: dict[str, Any] = {"type": "x_search"}
        if allowed:
            tool_spec["allowed_x_handles"] = allowed
        if excluded:
            tool_spec["excluded_x_handles"] = excluded
        for key in ("from_date", "to_date"):
            if getattr(args, key):
                tool_spec[key] = getattr(args, key)
        if args.enable_image_understanding:
            tool_spec["enable_image_understanding"] = True
        if args.enable_video_understanding:
            tool_spec["enable_video_understanding"] = True
        try:
            session = await provider.token_manager().session()
            res = await provider.http.post(
                f"{API}/responses",
                headers=provider.headers(session, **{"content-type": "application/json"}),
                json={
                    "model": SEARCH_MODEL,
                    "input": [{"role": "user", "content": args.query}],
                    "tools": [tool_spec],
                    "store": False,
                },
                timeout=120,
            )
        except (LlmError, httpx.HTTPError) as exc:
            return f"Error: {exc}"
        if res.status_code >= 400:
            return f"Error: {http_error('grok x_search', res.status_code, res.text)}"
        data = res.json()
        answer = str(data.get("output_text") or "").strip()
        citations: list[str] = [str(c) for c in data.get("citations") or [] if isinstance(c, str)]
        if not answer:
            texts = []
            for item in data.get("output") or []:
                if item.get("type") == "message":
                    for block in item.get("content") or []:
                        if block.get("type") in ("output_text", "text") and block.get("text"):
                            texts.append(str(block["text"]))
                        for ann in block.get("annotations") or []:
                            if ann.get("type") == "url_citation" and ann.get("url"):
                                citations.append(str(ann["url"]))
            answer = "\n\n".join(texts)
        seen: set[str] = set()
        urls = [u for u in citations if not (u in seen or seen.add(u))]
        return answer + ("\n\nSources:\n" + "\n".join(f"- {u}" for u in urls) if urls else "")

    @tool(
        "grok_image_generate",
        description=dedent(
            """
            Generate an image with grok-imagine-image-2.0 through the Grok subscription, or edit local reference
            images. Saves the images and returns their paths and preview URLs.
            """
        ).strip(),
        args_schema=ImageArgs,
    )
    async def grok_image_generate(**kwargs: Any) -> str:
        if not service.tool_enabled("grok", "image_generate", at_creation=True):
            return "Error: grok_image_generate is disabled on the AI subscriptions page"
        args = ImageArgs(**kwargs)
        refs = []
        for path in args.referenced_image_paths or []:
            try:
                refs.append(read_reference(path)[1])
            except Exception as exc:  # noqa: BLE001
                return f"Error: cannot read reference image {path}: {exc}"
        body: dict[str, Any] = {"prompt": args.prompt, "model": IMAGE_MODEL, "response_format": "b64_json"}
        if args.size:
            body["aspect_ratio"] = ASPECT[args.size]
        if args.quality in ("low", "medium", "high"):
            body["quality"] = "low" if args.quality == "low" else "medium"
        if len(refs) == 1:
            body["image"] = {"type": "image_url", "url": refs[0]}
        elif refs:
            body["images"] = [{"type": "image_url", "url": r} for r in refs]
        try:
            session = await provider.token_manager().session()
            headers = {
                "authorization": f"Bearer {session['accessToken']}",
                "content-type": "application/json",
                "accept": "application/json",
            }
            images = await generate_images(
                provider.http, f"{API}/images/{'edits' if refs else 'generations'}", headers, body, "grok images"
            )
        except LlmError as exc:
            return f"Error: {exc}"
        paths, revised = save_images(service.media, images)
        return describe_images(paths, revised, service.media_url)

    @tool(
        "grok_video_generate",
        description=dedent(
            """
            Generate a 1–15 second video with grok-imagine-video-1.5 through the Grok subscription (text-to-video,
            or image-to-video with image_url). Saves an MP4 and returns its path and preview URL.
            """
        ).strip(),
        args_schema=VideoArgs,
    )
    async def grok_video_generate(**kwargs: Any) -> str:
        if not service.tool_enabled("grok", "video_generate", at_creation=True):
            return "Error: grok_video_generate is disabled on the AI subscriptions page"
        args = VideoArgs(**kwargs)
        body: dict[str, Any] = {"prompt": args.prompt, "model": VIDEO_MODEL}
        for key in ("duration", "aspect_ratio", "resolution"):
            if getattr(args, key) is not None:
                body[key] = getattr(args, key)
        if args.image_url:
            body["image"] = {"url": args.image_url}
        try:
            session = await provider.token_manager().session()
        except LlmError as exc:
            return f"Error: {exc}"
        headers = {
            "authorization": f"Bearer {session['accessToken']}",
            "accept": "application/json",
            "content-type": "application/json",
        }
        res = await provider.http.post(f"{API}/videos/generations", headers=headers, json=body, timeout=60)
        if res.status_code >= 400:
            return f"Error: {http_error('grok video', res.status_code, res.text)}"
        request_id = str(res.json().get("request_id") or "")
        if not request_id:
            return "Error: Grok returned no request id"
        deadline = time.time() + 600
        video: dict[str, Any] = {}
        while True:
            await asyncio.sleep(3)
            poll = await provider.http.get(
                f"{API}/videos/{quote(request_id, safe='')}",
                headers={"authorization": headers["authorization"], "accept": "application/json"},
                timeout=30,
            )
            if poll.status_code >= 400:
                return f"Error: {http_error('grok video', poll.status_code, poll.text)}"
            data = poll.json()
            status = data.get("status")
            if status == "done":
                video = data.get("video") or {}
                break
            if status in ("failed", "expired"):
                err = data.get("error")
                return f"Error: video generation {status}: {err.get('message') if isinstance(err, dict) else err or ''}"
            if status != "pending":
                return f"Error: unexpected video status {status!r}"
            if time.time() > deadline:
                return "Error: video generation timed out after 10 minutes"
        url = str(video.get("url") or "")
        if not url:
            return "Error: Grok returned no video URL"
        download = await provider.http.get(url, timeout=300, follow_redirects=True)
        if download.status_code >= 400:
            return f"Error: video download failed (HTTP {download.status_code})"
        path = service.media.video_path()
        path.write_bytes(download.content)
        duration = video.get("duration")
        return dedent(
            f"""
            Saved video to {path}{f" ({duration}s)" if duration else ""}
            Preview URL: {service.media_url(path)}
            Temporary provider URL (expires soon): {url}
            """
        ).strip()

    return [grok_x_search, grok_image_generate, grok_video_generate]
