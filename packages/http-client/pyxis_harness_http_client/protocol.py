from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

import httpx

from pyxis_harness import package_toml

_CFG = package_toml(__file__)["protocol"]
DIRECT_TARGET_ID: str = _CFG["DIRECT_TARGET_ID"]
HTTP_METHODS: tuple[str, ...] = tuple(_CFG["HTTP_METHODS"])
SAFE_METHODS: tuple[str, ...] = tuple(_CFG["SAFE_METHODS"])
HTTP_AUTH_TYPES: tuple[str, ...] = tuple(_CFG["HTTP_AUTH_TYPES"])
HTTP_BODY_MODES: tuple[str, ...] = tuple(_CFG["HTTP_BODY_MODES"])
DEFAULT_TIMEOUT_MS: int = _CFG["DEFAULT_TIMEOUT_MS"]
MIN_TIMEOUT_MS: int = _CFG["MIN_TIMEOUT_MS"]
MAX_TIMEOUT_MS: int = _CFG["MAX_TIMEOUT_MS"]
DEFAULT_HISTORY_LIMIT: int = _CFG["DEFAULT_HISTORY_LIMIT"]
MIN_HISTORY_LIMIT: int = _CFG["MIN_HISTORY_LIMIT"]
MAX_HISTORY_LIMIT: int = _CFG["MAX_HISTORY_LIMIT"]
PANEL_BODY_BYTES: int = _CFG["PANEL_BODY_BYTES"]
HISTORY_BODY_BYTES: int = _CFG["HISTORY_BODY_BYTES"]

VARIABLE = re.compile(r"\{\{\s*([A-Za-z_][A-Za-z0-9_.-]*)\s*\}\}")
SCHEME = re.compile(r"^[a-z][a-z0-9+.-]*://", re.IGNORECASE)
LOCAL_LITERAL = re.compile(r"^(localhost|127\.|10\.|192\.168\.|0\.0\.0\.0|\[)", re.IGNORECASE)
LINE_END = re.compile(r"\r\n|\n|\r")

Pairs = list[tuple[str, str]]


def is_method(value: Any) -> bool:
    return isinstance(value, str) and value in HTTP_METHODS


def is_event_stream(content_type: str) -> bool:
    return content_type.split(";", maxsplit=1)[0].strip().lower() == "text/event-stream"


def to_pairs(value: Any) -> Pairs:
    if value is None:
        return []
    items = value.items() if isinstance(value, Mapping) else value
    return [(str(name), str(item)) for name, item in items]


def substitute(text: str, variables: Mapping[str, str]) -> str:
    return VARIABLE.sub(lambda m: variables[m.group(1)] if m.group(1) in variables else m.group(0), text)


def _parse(text: str, shown: str) -> httpx.URL:
    try:
        url = httpx.URL(text)
    except (httpx.InvalidURL, ValueError, TypeError) as exc:
        raise ValueError(f"invalid URL '{shown}'") from exc
    if not url.host:
        raise ValueError(f"invalid URL '{shown}'")
    return url


def join_url(base_url: str, path: str, query: Any) -> httpx.URL:
    """
    The URL the engine sends and the page previews. An empty base URL (a request without a target) takes the path
    as the whole URL: a missing scheme becomes ``http`` for loopback and private literals, ``https`` otherwise.
    Raises ``ValueError`` on a malformed URL, a scheme other than http(s) or embedded credentials.
    """
    if SCHEME.match(path):
        url = _parse(path, path)
    elif not base_url:
        bare = path.strip()
        if not bare:
            raise ValueError("URL is required")
        if bare.startswith("/"):
            raise ValueError("enter a full URL, e.g. https://api.example.com/users")
        url = _parse(f"{'http' if LOCAL_LITERAL.match(bare) else 'https'}://{bare}", path)
    else:
        base = httpx.URL(base_url)
        path_part, _, rest = path.partition("?")
        base_path = base.path.rstrip("/")
        relative = path_part.lstrip("/")
        joined = f"{base_path}/{relative}" if relative else (base_path or "/")
        url = _parse(f"{base.scheme}://{base.netloc.decode()}{joined}{'?' + rest if rest else ''}", path)
    if url.scheme not in ("http", "https"):
        raise ValueError("only http(s) URLs are supported")
    if url.userinfo:
        raise ValueError("URL credentials are not supported; use the target auth setting")
    for name, value in to_pairs(query):
        url = url.copy_add_param(name, value)
    return url.copy_with(fragment=None)


class SseParser:
    """
    Lines end with LF, CR or CRLF; ``:`` lines are comments; a blank line dispatches the event built from the
    ``event``, ``data``, ``id`` and ``retry`` fields since the previous one. An event without a field is not
    dispatched.
    """

    def __init__(self) -> None:
        self._buffer = ""
        self._reset()

    def _reset(self) -> None:
        self._event = ""
        self._data: list[str] = []
        self._id: str | None = None
        self._retry: int | None = None
        self._touched = False

    def push(self, chunk: str) -> list[dict[str, Any]]:
        """Feed decoded text; returns the events it completes."""
        self._buffer += chunk
        out = []
        while True:
            match = LINE_END.search(self._buffer)
            # A CR that ends the buffer may be the first half of a CRLF still in transit.
            if match is None or (match.group(0) == "\r" and match.end() == len(self._buffer)):
                break
            line, self._buffer = self._buffer[: match.start()], self._buffer[match.end() :]
            event = self._line(line)
            if event is not None:
                out.append(event)
        return out

    def flush(self) -> list[dict[str, Any]]:
        """End of stream: the unterminated last line and the pending event, when there is one."""
        rest, self._buffer = self._buffer.removesuffix("\r"), ""
        events = [self._line(rest)] if rest else []
        events.append(self._dispatch())
        return [event for event in events if event is not None]

    def _line(self, line: str) -> dict[str, Any] | None:
        if not line:
            return self._dispatch()
        if line.startswith(":"):
            return None
        field, _, value = line.partition(":")
        value = value.removeprefix(" ")
        if field == "event":
            self._event, self._touched = value, True
        elif field == "data":
            self._data.append(value)
            self._touched = True
        elif field == "id" and "\0" not in value:
            self._id, self._touched = value, True
        elif field == "retry" and value.isascii() and value.isdigit():
            self._retry, self._touched = int(value), True
        return None

    def _dispatch(self) -> dict[str, Any] | None:
        if not self._touched:
            return None
        event: dict[str, Any] = {"event": self._event, "data": "\n".join(self._data)}
        if self._id is not None:
            event["id"] = self._id
        if self._retry is not None:
            event["retry"] = self._retry
        self._reset()
        return event


def parse_sse(text: str) -> list[dict[str, Any]]:
    parser = SseParser()
    return [*parser.push(text), *parser.flush()]
