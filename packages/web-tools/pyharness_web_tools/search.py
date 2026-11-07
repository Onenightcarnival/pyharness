"""``web_search``: DeepSeek native search through one Anthropic-format Messages call.

| function                    | contract                                                                       |
|-----------------------------|--------------------------------------------------------------------------------|
| ``search()``                | ``{"answer", "sources", "truncated"}``; ``RuntimeError`` with a user-facing message on |
|                             | failure                                                                        |
| ``parse_search_response()`` | answer text and deduplicated sources of a response with ``web_search_tool_result`` |
|                             | blocks                                                                         |
| ``format_search()``         | the tool result: notice, answer, ``Sources:`` list, citation instruction        |
| ``search_tool()``           | the ``web_search`` LangChain tool bound to the service                          |
"""

from __future__ import annotations

from string import Template
from typing import Any
from urllib.parse import urlparse

import httpx
from langchain_core.tools import tool

from pyharness import package_prompts

from .common import NOTICE, Host

PROMPTS = package_prompts(__file__)


def format_search(answer: str, sources: list[dict[str, Any]], truncated: bool) -> str:
    parts = [NOTICE]
    if answer.strip():
        parts.append(answer.strip())
    if sources:
        lines = []
        for s in sources:
            label = s.get("title") or (urlparse(s["url"]).hostname or s["url"])
            meta = " ".join(
                x for x in [s.get("snippet", ""), f"({s['published_at']})" if s.get("published_at") else ""] if x
            )
            lines.append(f"- [{label}]({s['url']})" + (f" — {meta}" if meta else ""))
        parts.append("Sources:\n" + "\n".join(lines))
    elif not answer.strip():
        parts.append("No results found.")
    if truncated:
        parts.append(f"(Showing the first {len(sources)} sources. Refine the query for more.)")
    parts.append("Cite the relevant URLs above as markdown links in your answer.")
    return "\n\n".join(parts)


def parse_search_response(body: dict[str, Any]) -> tuple[str, list[dict[str, Any]]]:
    """Answer text and deduplicated sources of a DeepSeek Messages response with ``web_search_tool_result`` blocks."""
    blocks = body.get("content") or []
    snippets: dict[str, str] = {}
    answer: list[str] = []
    for block in blocks:
        if block.get("type") != "text":
            continue
        if block.get("text"):
            answer.append(str(block["text"]))
        for cite in block.get("citations") or []:
            url, cited = cite.get("url"), cite.get("cited_text")
            if url and cited and url not in snippets:
                snippets[url] = str(cited).strip()
    sources: list[dict[str, Any]] = []
    seen: set[str] = set()
    for block in blocks:
        if block.get("type") != "web_search_tool_result":
            continue
        for item in block.get("content") or []:
            url = item.get("url") if isinstance(item, dict) else None
            if item.get("type") != "web_search_result" or not url or url in seen:
                continue
            seen.add(url)
            source = {"url": url}
            if item.get("title"):
                source["title"] = str(item["title"])
            if url in snippets:
                source["snippet"] = snippets[url]
            if item.get("page_age"):
                source["published_at"] = str(item["page_age"])
            sources.append(source)
    return "".join(answer), sources


async def search(service: Host, query: str) -> dict[str, Any]:
    """``{"answer", "sources", "truncated"}``; raises ``RuntimeError`` with a user-facing message on failure."""
    config = service.config
    key = service.api_key()
    if not key:
        raise RuntimeError(Template(PROMPTS["search"]["no_api_key"]).substitute(api_key_env=config.api_key_env))
    body = {
        "model": config.model,
        "max_tokens": config.max_tokens,
        "messages": [
            {"role": "user", "content": [{"type": "text", "text": f"Perform a web search for the query: {query}"}]}
        ],
        "tools": [{"type": "web_search_20250305", "name": "web_search", "max_uses": config.max_uses}],
        "thinking": {"type": "disabled"},
    }
    endpoint = config.base_url.rstrip("/") + "/messages"
    headers = {
        "x-api-key": key,
        "authorization": f"Bearer {key}",
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
        "accept": "application/json",
    }
    async with service.client(config.search_timeout) as client:
        try:
            response = await client.post(endpoint, json=body, headers=headers)
        except httpx.HTTPError as exc:
            raise RuntimeError(f"DeepSeek search request failed ({endpoint}): {exc}") from exc
    if response.status_code >= 400:
        detail = ""
        try:
            err = response.json().get("error")
            detail = err if isinstance(err, str) else (err or {}).get("message") or ""
        except Exception:  # noqa: BLE001
            detail = response.text[:300]
        raise RuntimeError(
            f"DeepSeek API error (HTTP {response.status_code}){': ' + detail if detail else ''} at {endpoint}"
        )
    try:
        answer, sources = parse_search_response(response.json())
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"DeepSeek returned an unprocessable response: {exc}") from exc
    if not sources and not answer:
        raise RuntimeError("DeepSeek returned no search results; the request may not have triggered native web search")
    truncated = len(sources) > config.max_results
    return {"answer": answer, "sources": sources[: config.max_results], "truncated": truncated}


def search_tool(service: Host) -> Any:
    @tool("web_search", description=PROMPTS["tools"]["web_search"])
    async def web_search(query: str) -> str:
        query = (query or "").strip()
        if not query:
            return "Error: query must be a non-empty string."
        try:
            result = await search(service, query)
        except RuntimeError as exc:
            return f"Error: {exc}"
        return format_search(result["answer"], result["sources"], result["truncated"])

    return web_search
