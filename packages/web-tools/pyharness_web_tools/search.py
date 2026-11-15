"""
``web_search``: DeepSeek search.

| ``search_provider``     | request                                                                         |
|-------------------------|---------------------------------------------------------------------------------|
| ``deepseek-search-api`` | ``POST {search_base_url}/search`` ``{query, count, need_content: false}``: one  |
|                         | direct request, paced to ``search_requests_per_second``; sources carry a summary |
| ``deepseek-legacy``     | one Anthropic-format Messages call with the ``web_search_20250305`` server tool: |
|                         | an answer with cited sources                                                    |

| function                    | contract                                                                       |
|-----------------------------|--------------------------------------------------------------------------------|
| ``search()``                | ``{"answer", "sources", "truncated"}``; ``RuntimeError`` with a user-facing message on |
|                             | failure                                                                        |
| ``map_search_response()``   | sources of a Search API response: url, title, snippet, summary, published_at   |
| ``parse_search_response()`` | answer text and deduplicated sources of a Messages response with                |
|                             | ``web_search_tool_result`` blocks                                               |
| ``format_search()``         | the tool result: notice, answer, ``Sources:`` list with each source's summary  |
|                             | or snippet, citation instruction                                               |
| ``search_tool()``           | the ``web_search`` LangChain tool bound to the service                          |

A redirect of the Search API endpoint and an HTTP 429 fail the search.
"""

from __future__ import annotations

import re
from string import Template
from typing import Any
from urllib.parse import urlparse

import httpx
from langchain_core.tools import tool

from pyharness import package_prompts

from .common import NOTICE, Host

PROMPTS = package_prompts(__file__)
ELLIPSIS = "…"


def format_search(answer: str, sources: list[dict[str, Any]], truncated: bool) -> str:
    parts = [NOTICE]
    if answer.strip():
        parts.append(answer.strip())
    if sources:
        lines = []
        for s in sources:
            label = s.get("title") or (urlparse(s["url"]).hostname or s["url"])
            excerpt = s.get("summary") or s.get("snippet", "")
            meta = " ".join(x for x in [excerpt, f"({s['published_at']})" if s.get("published_at") else ""] if x)
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


def _bounded(text: str, limit: int) -> str:
    """``text`` with whitespace collapsed, cut to ``limit`` characters including the ellipsis that marks a cut."""
    text = re.sub(r"\s+", " ", text).strip()
    return text if len(text) <= limit else text[: limit - len(ELLIPSIS)] + ELLIPSIS


def map_search_response(body: Any, summary_max_chars: int) -> list[dict[str, Any]]:
    """Sources of a Search API response, in provider order; raises ``ValueError`` on an invalid body."""
    results = body.get("results") if isinstance(body, dict) else None
    if not isinstance(results, list):
        raise ValueError("no results list")
    sources = []
    for item in results:
        if not isinstance(item, dict) or not isinstance(item.get("url"), str) or not item["url"]:
            raise ValueError("a result without a url")
        source = {"url": item["url"]}
        for field, key in (("title", "title"), ("snippet", "snippet"), ("date", "published_at")):
            if isinstance(item.get(field), str) and item[field]:
                source[key] = item[field]
        if isinstance(item.get("summary"), str) and item["summary"].strip():
            source["summary"] = _bounded(item["summary"], summary_max_chars)
        sources.append(source)
    return sources


def _error_detail(response: httpx.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        return response.text[:300]
    if not isinstance(body, dict):
        return ""
    err = body.get("error")
    detail = err if isinstance(err, str) else err.get("message") if isinstance(err, dict) else body.get("message")
    return detail if isinstance(detail, str) else ""


def _http_error(response: httpx.Response, endpoint: str) -> RuntimeError:
    detail = _error_detail(response)
    return RuntimeError(
        f"DeepSeek API error (HTTP {response.status_code}){': ' + detail if detail else ''} at {endpoint}"
    )


async def _search_api(service: Host, query: str, key: str) -> dict[str, Any]:
    config = service.config
    endpoint = config.search_base_url.rstrip("/") + "/search"
    body = {"query": query, "count": config.max_results, "need_content": False}
    headers = {"authorization": f"Bearer {key}", "content-type": "application/json", "accept": "application/json"}
    await service.pacer.wait(config.search_requests_per_second)
    async with service.client(config.search_timeout) as client:
        try:
            response = await client.post(endpoint, json=body, headers=headers, follow_redirects=False)
        except httpx.HTTPError as exc:
            raise RuntimeError(f"DeepSeek search request failed ({endpoint}): {exc}") from exc
    if not response.is_success:
        raise _http_error(response, endpoint)
    try:
        sources = map_search_response(response.json(), config.summary_max_chars)
    except ValueError as exc:
        raise RuntimeError(f"DeepSeek returned an invalid response body: {exc}") from exc
    return {"answer": "", "sources": sources[: config.max_results], "truncated": False}


async def _search_legacy(service: Host, query: str, key: str) -> dict[str, Any]:
    config = service.config
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
        raise _http_error(response, endpoint)
    try:
        answer, sources = parse_search_response(response.json())
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"DeepSeek returned an unprocessable response: {exc}") from exc
    if not sources and not answer:
        raise RuntimeError("DeepSeek returned no search results; the request may not have triggered native web search")
    truncated = len(sources) > config.max_results
    return {"answer": answer, "sources": sources[: config.max_results], "truncated": truncated}


async def search(service: Host, query: str) -> dict[str, Any]:
    """``{"answer", "sources", "truncated"}``; raises ``RuntimeError`` with a user-facing message on failure."""
    config = service.config
    key = service.api_key()
    if not key:
        raise RuntimeError(Template(PROMPTS["search"]["no_api_key"]).substitute(api_key_env=config.api_key_env))
    if config.search_provider == "deepseek-legacy":
        return await _search_legacy(service, query, key)
    return await _search_api(service, query, key)


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
