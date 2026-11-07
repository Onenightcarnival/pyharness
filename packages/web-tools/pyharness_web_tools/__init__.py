"""``ctx.web``: the ``web_search`` and ``web_fetch`` tools.

| tool           | source                                                                                  |
|----------------|-----------------------------------------------------------------------------------------|
| ``web_search`` | DeepSeek native search: one Anthropic-format Messages call with the ``web_search_20250305`` server |
|                | tool; the answer text plus the cited sources (url, title, snippet, date)                |
| ``web_fetch``  | HTTP GET; HTML reduced to text (links kept as ``[text](url)``), JSON and text verbatim, truncated |
|                | to ``fetch_max_chars``                                                                  |

The search key is the ``api_key_env`` credential (``DEEPSEEK_API_KEY``): the environment first, then the profile's
credential store (Settings → Models writes it for the DeepSeek route). Without it ``web_search`` answers with the
instruction to add it rather than failing the turn. Both tools prefix their output with a notice that marks it as
untrusted external content.
"""

from .fetch import html_to_text
from .search import format_search, parse_search_response
from .service import Config, WebToolsService

__all__ = ["Config", "WebToolsService", "format_search", "html_to_text", "parse_search_response"]
