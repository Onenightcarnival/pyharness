"""Generated media: saving images / videos under the subscriptions data directory and describing them to the model."""

from __future__ import annotations

import base64
import json
from pathlib import Path
from string import Template
from typing import Any

import httpx

from pyharness import package_prompts

from .common import LlmError, http_error
from .store import MediaStore, image_extension

PROMPTS = package_prompts(__file__)["media"]


async def generate_images(
    http: httpx.AsyncClient, url: str, headers: dict[str, str], body: dict[str, Any], label: str
) -> list[tuple[bytes, str | None]]:
    """POST an OpenAI-style image request; returns ``[(bytes, revised_prompt)]``."""
    res = await http.post(url, headers=headers, json=body, timeout=180)
    if res.status_code >= 400:
        raise http_error(label, res.status_code, res.text)
    out = []
    for item in res.json().get("data") or []:
        b64 = item.get("b64_json")
        if b64:
            out.append((base64.b64decode(b64), item.get("revised_prompt")))
    if not out:
        raise LlmError("EMPTY_RESPONSE", f"{label} returned no images")
    return out


def save_images(media: MediaStore, images: list[tuple[bytes, str | None]]) -> tuple[list[Path], str | None]:
    paths = []
    revised = None
    for index, (data, prompt) in enumerate(images):
        path = media.image_path(index, image_extension(data))
        path.write_bytes(data)
        paths.append(path)
        revised = revised or prompt
    return paths, revised


def describe_images(paths: list[Path], revised: str | None, url_of: Any) -> str:
    lines = [Template(PROMPTS["saved_images"]).substitute(count=len(paths))] + [f"- {p}" for p in paths]
    refs = [
        {
            "path": str(p),
            "url": url_of(p),
            "mediaType": {"png": "image/png", "jpg": "image/jpeg", "webp": "image/webp", "gif": "image/gif"}.get(
                p.suffix.lstrip("."), "image/png"
            ),
            "bytes": p.stat().st_size,
        }
        for p in paths
    ]
    lines += ["", Template(PROMPTS["image_references"]).substitute(refs=json.dumps(refs, ensure_ascii=False))]
    links = " ".join(f"![{p.name}]({url_of(p)})" for p in paths)
    lines += ["", Template(PROMPTS["show_images"]).substitute(links=links)]
    if revised:
        lines += ["", Template(PROMPTS["revised_prompt"]).substitute(revised=revised)]
    return "\n".join(lines)


def read_reference(path: str) -> tuple[str, str]:
    """``(mime, data_url)`` of a local image file given as a reference."""
    p = Path(path).expanduser()
    data = p.read_bytes()
    ext = image_extension(data)
    mime = {"png": "image/png", "jpg": "image/jpeg", "webp": "image/webp", "gif": "image/gif"}[ext]
    return mime, f"data:{mime};base64,{base64.b64encode(data).decode()}"


def format_search(content: str, sources: list[dict[str, Any]], truncated: bool) -> str:
    parts = [PROMPTS["untrusted"]]
    if content:
        parts.append(content)
    if sources:
        parts.append(
            PROMPTS["sources"]
            + "\n"
            + "\n".join(
                f'- "{s.get("title") or s["url"]}": {s["url"]}' + (f" — {s['snippet']}" if s.get("snippet") else "")
                for s in sources
            )
        )
    if not content and not sources:
        parts.append(PROMPTS["no_results"])
    if truncated:
        parts.append(PROMPTS["truncated"])
    parts.append(PROMPTS["cite"])
    return "\n\n".join(parts)


def dedupe_sources(raw: list[dict[str, Any]], limit: int | None = None) -> list[dict[str, Any]]:
    seen: set[str] = set()
    out = []
    for item in raw:
        url = str(item.get("url") or item.get("source_url") or item.get("uri") or "")
        if not url.startswith(("http://", "https://")) or url in seen:
            continue
        seen.add(url)
        entry: dict[str, Any] = {"url": url}
        title = item.get("title") or item.get("source_title")
        if title:
            entry["title"] = str(title)[:1000]
        snippet = item.get("snippet") or item.get("text")
        if snippet:
            entry["snippet"] = str(snippet)[:4000]
        out.append(entry)
        if limit and len(out) >= limit:
            break
    return out
