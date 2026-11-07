"""``web_fetch``: HTTP GET with the body reduced to readable text.

| function           | contract                                                                             |
|--------------------|--------------------------------------------------------------------------------------|
| ``html_to_text()`` | ``(title, text)`` of an HTML document: headings, bullets, paragraphs, links as ``[text](url)`` |
| ``fetch()``        | ``{"url", "status", "content_type", "title", "text", "truncated"}``; ``RuntimeError`` on |
|                    | failure                                                                              |
| ``fetch_tool()``   | the ``web_fetch`` LangChain tool bound to the service                                 |

The body is read up to ``fetch_max_bytes``; HTML becomes text, JSON is re-indented, other text kinds pass verbatim,
binary content is described, and the text is cut at ``max_chars`` (at most ``fetch_max_chars``).
"""

from __future__ import annotations

import contextlib
import html
import json
import re
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx
from langchain_core.tools import tool

from pyharness import package_prompts

from .common import NOTICE, Host

PROMPTS = package_prompts(__file__)

BLOCK_TAGS = {
    "p",
    "div",
    "section",
    "article",
    "header",
    "footer",
    "main",
    "aside",
    "nav",
    "ul",
    "ol",
    "table",
    "tr",
    "br",
    "hr",
    "blockquote",
    "pre",
    "dl",
    "dt",
    "dd",
    "figure",
    "figcaption",
    "form",
    "fieldset",
}
SKIP_TAGS = {"script", "style", "noscript", "template", "svg", "iframe", "canvas", "object"}
HEADINGS = {"h1": "#", "h2": "##", "h3": "###", "h4": "####", "h5": "#####", "h6": "######"}


class _TextExtractor(HTMLParser):
    """HTML → readable text: headings, list bullets, paragraphs and links; scripts, styles and markup noise dropped."""

    def __init__(self, base: str) -> None:
        super().__init__(convert_charrefs=True)
        self.base = base
        self.parts: list[str] = []
        self.skip = 0
        self.link: str | None = None
        self.link_text: list[str] = []
        self.title: str | None = None
        self.in_title = False
        self.pre = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in SKIP_TAGS:
            self.skip += 1
            return
        if self.skip:
            return
        if tag == "title":
            self.in_title = True
        elif tag in HEADINGS:
            self.parts.append(f"\n\n{HEADINGS[tag]} ")
        elif tag == "li":
            self.parts.append("\n- ")
        elif tag == "pre":
            self.pre += 1
            self.parts.append("\n\n```\n")
        elif tag in BLOCK_TAGS:
            self.parts.append("\n\n" if tag != "br" else "\n")
        elif tag == "a":
            href = dict(attrs).get("href")
            if href and not href.startswith(("#", "javascript:", "mailto:")):
                self.link = urljoin(self.base, href)
                self.link_text = []
        elif tag == "img":
            alt = dict(attrs).get("alt")
            if alt:
                self.parts.append(f" [image: {alt.strip()}] ")

    def handle_endtag(self, tag: str) -> None:
        if tag in SKIP_TAGS:
            self.skip = max(0, self.skip - 1)
            return
        if self.skip:
            return
        if tag == "title":
            self.in_title = False
        elif tag == "pre":
            self.pre = max(0, self.pre - 1)
            self.parts.append("\n```\n\n")
        elif tag in HEADINGS or tag in BLOCK_TAGS:
            self.parts.append("\n")
        elif tag == "a" and self.link is not None:
            text = "".join(self.link_text).strip()
            if text:
                self.parts.append(f"[{text}]({self.link})")
            self.link = None
            self.link_text = []

    def handle_data(self, data: str) -> None:
        if self.skip:
            return
        if self.in_title:
            self.title = (self.title or "") + data
            return
        if self.link is not None:
            self.link_text.append(data)
            return
        self.parts.append(data if self.pre else re.sub(r"\s+", " ", data))

    def text(self) -> str:
        raw = "".join(self.parts)
        raw = re.sub(r"[ \t]+\n", "\n", raw)
        raw = re.sub(r"\n{3,}", "\n\n", raw)
        return raw.strip()


def html_to_text(markup: str, base: str = "") -> tuple[str | None, str]:
    """``(title, text)`` of an HTML document."""
    parser = _TextExtractor(base)
    parser.feed(markup)
    parser.close()
    title = html.unescape(parser.title).strip() if parser.title else None
    return title or None, parser.text()


async def fetch(service: Host, url: str, max_chars: int | None = None) -> dict[str, Any]:
    """``{"url", "status", "content_type", "title", "text", "truncated"}``; raises ``RuntimeError`` on failure."""
    config = service.config
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise RuntimeError(f"web_fetch needs an http(s) URL; got {url!r}")
    limit = max(1, min(max_chars or config.fetch_max_chars, config.fetch_max_chars))
    async with service.client(config.fetch_timeout) as client:
        try:
            async with client.stream(
                "GET",
                url,
                headers={"accept": "text/html,application/xhtml+xml,application/json,text/plain;q=0.9,*/*;q=0.5"},
            ) as response:
                chunks: list[bytes] = []
                size = 0
                async for chunk in response.aiter_bytes():
                    chunks.append(chunk)
                    size += len(chunk)
                    if size >= config.fetch_max_bytes:
                        break
                raw = b"".join(chunks)
                status = response.status_code
                content_type = response.headers.get("content-type", "")
                final_url = str(response.url)
                encoding = response.encoding or "utf-8"
        except httpx.HTTPError as exc:
            raise RuntimeError(f"fetching {url} failed: {exc}") from exc
    kind = content_type.split(";")[0].strip().lower()
    title = None
    if kind in ("text/html", "application/xhtml+xml") or (not kind and raw[:512].lower().lstrip().startswith(b"<")):
        title, text = html_to_text(raw.decode(encoding, errors="replace"), final_url)
    elif (
        kind.startswith("text/")
        or kind in ("application/json", "application/xml", "application/javascript")
        or kind.endswith(("+json", "+xml"))
    ):
        text = raw.decode(encoding, errors="replace")
        if kind == "application/json":
            with contextlib.suppress(ValueError):
                text = json.dumps(json.loads(text), ensure_ascii=False, indent=2)
    else:
        text = f"(binary content: {kind or 'unknown type'}, {size} bytes; not shown)"
    truncated = len(text) > limit
    return {
        "url": final_url,
        "status": status,
        "content_type": kind,
        "title": title,
        "text": text[:limit],
        "truncated": truncated,
    }


def fetch_tool(service: Host) -> Any:
    @tool("web_fetch", description=PROMPTS["tools"]["web_fetch"])
    async def web_fetch(url: str, max_chars: int | None = None) -> str:
        try:
            r = await fetch(service, url, max_chars)
        except RuntimeError as exc:
            return f"Error: {exc}"
        head = f"{NOTICE}\n\nURL: {r['url']}\nStatus: {r['status']}" + (f"\nTitle: {r['title']}" if r["title"] else "")
        tail = "\n\n(truncated; ask for a larger max_chars or fetch a more specific page)" if r["truncated"] else ""
        return f"{head}\n\n{r['text']}{tail}"

    return web_fetch
