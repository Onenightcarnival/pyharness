"""``ctx.web``: the ``web_search`` and ``web_fetch`` tools.

| tool           | source                                                                                  |
|----------------|-----------------------------------------------------------------------------------------|
| ``web_search`` | DeepSeek Search API: one direct request per search; the sources with title, url, summary and |
|                | date. ``search_provider: deepseek-legacy`` keeps the earlier path: a Messages call with the |
|                | ``web_search_20250305`` server tool, an answer text plus the cited sources              |
| ``web_fetch``  | HTTP GET; HTML reduced to text (links kept as ``[text](url)``), JSON and text verbatim, truncated |
|                | to ``fetch_max_chars``                                                                  |

| config                          | meaning                                                              |
|---------------------------------|----------------------------------------------------------------------|
| ``search_provider``             | ``deepseek-search-api`` (default) or ``deepseek-legacy``             |
| ``search_base_url``             | Search API base, ``https://api.deepseek.com/v1/tools``; ``/search`` is appended |
| ``search_requests_per_second``  | Search API requests started per second (5, the account-wide limit)   |
| ``max_results``                 | sources returned per search (10)                                     |
| ``summary_max_chars``           | cap of one source summary in the tool result (800)                   |
| ``base_url``, ``model``, ``max_uses``, ``max_tokens`` | the Messages endpoint and model of ``deepseek-legacy`` |

The search key is the ``api_key_env`` credential (``DEEPSEEK_API_KEY``): the environment first, then the profile's
credential store (Settings → Models writes it for the DeepSeek route). Without it ``web_search`` answers with the
instruction to add it rather than failing the turn. Both tools prefix their output with a notice that marks it as
untrusted external content.
"""

from __future__ import annotations

from .config import Config
from .fetch import html_to_text
from .search import format_search, map_search_response, parse_search_response
from .service import WebToolsService

__all__ = [
    "Config",
    "WebToolsService",
    "format_search",
    "html_to_text",
    "map_search_response",
    "parse_search_response",
]
