from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from typing import Any
from urllib.parse import quote_plus

import httpx

from pyxis_harness import package_toml

_CFG = package_toml(__file__)["protocol"]
DIRECT_TARGET_ID: str = _CFG["DIRECT_TARGET_ID"]
HTTP_METHODS: tuple[str, ...] = tuple(_CFG["HTTP_METHODS"])
SAFE_METHODS: tuple[str, ...] = tuple(_CFG["SAFE_METHODS"])
HTTP_AUTH_TYPES: tuple[str, ...] = tuple(_CFG["HTTP_AUTH_TYPES"])
HTTP_BODY_MODES: tuple[str, ...] = tuple(_CFG["HTTP_BODY_MODES"])
HTTP_CAPTURE_SOURCES: tuple[str, ...] = tuple(_CFG["HTTP_CAPTURE_SOURCES"])
HTTP_CAPTURE_REFRESH: tuple[str, ...] = tuple(_CFG["HTTP_CAPTURE_REFRESH"])
MAX_CAPTURE_RULES: int = _CFG["MAX_CAPTURE_RULES"]
MAX_CAPTURE_TTL_SECONDS: int = _CFG["MAX_CAPTURE_TTL_SECONDS"]
DEFAULT_TIMEOUT_MS: int = _CFG["DEFAULT_TIMEOUT_MS"]
MIN_TIMEOUT_MS: int = _CFG["MIN_TIMEOUT_MS"]
MAX_TIMEOUT_MS: int = _CFG["MAX_TIMEOUT_MS"]
DEFAULT_HISTORY_LIMIT: int = _CFG["DEFAULT_HISTORY_LIMIT"]
MIN_HISTORY_LIMIT: int = _CFG["MIN_HISTORY_LIMIT"]
MAX_HISTORY_LIMIT: int = _CFG["MAX_HISTORY_LIMIT"]
PANEL_BODY_BYTES: int = _CFG["PANEL_BODY_BYTES"]
HISTORY_BODY_BYTES: int = _CFG["HISTORY_BODY_BYTES"]

VARIABLE = re.compile(r"\{\{\s*([A-Za-z_][A-Za-z0-9_.-]*)\s*\}\}")
VARIABLE_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_.-]{0,63}$")
# RFC 7230 token.
HEADER_NAME = re.compile(r"^[!#$%&'*+.^_`|~0-9A-Za-z-]+$")
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


def referenced_variables(texts: Iterable[str]) -> set[str]:
    """Names referenced as ``{{name}}`` in any of the texts."""
    return {match.group(1) for text in texts for match in VARIABLE.finditer(text)}


def blank_capture() -> dict[str, Any]:
    """A capture rule with every field at its default."""
    return {"name": "", "source": "body", "path": "", "enabled": True, "ttlSeconds": 0, "ttlPath": "", "refresh": "off"}


def saved_request_title(request: Mapping[str, Any]) -> str:
    """Its name, else its path, else its method."""
    return request["name"].strip() or request["path"].strip() or request["method"]


def _active_rows(rows: Iterable[Any]) -> Pairs:
    """Enabled rows with a name, as ``(name, value)`` pairs."""
    out: Pairs = []
    for row in rows:
        if not isinstance(row, Mapping) or row.get("enabled") is False:
            continue
        key, value = row.get("key"), row.get("value")
        if isinstance(key, str) and key.strip():
            out.append((key.strip(), value if isinstance(value, str) else ""))
    return out


def _form_encoded(pairs: Pairs) -> str:
    """``application/x-www-form-urlencoded`` as a browser's ``URLSearchParams`` serializes it."""
    return "&".join(
        f"{quote_plus(name, safe='*').replace('~', '%7E')}={quote_plus(value, safe='*').replace('~', '%7E')}"
        for name, value in pairs
    )


def request_input_of(form: Mapping[str, Any]) -> dict[str, Any]:
    """
    The request input a saved request form sends: enabled rows with a name, the body of the selected mode and its
    default content type.
    """
    method = form["method"]
    headers = dict(_active_rows(form["headers"]))
    body: str | None = None
    kind: str | None = None
    if method not in ("GET", "HEAD"):
        if form["bodyMode"] in ("json", "text") and form["body"]:
            body = form["body"]
            kind = "application/json" if form["bodyMode"] == "json" else "text/plain"
        elif form["bodyMode"] == "form":
            body, kind = _form_encoded(_active_rows(form["form"])), "application/x-www-form-urlencoded"
    if kind is not None and not any(name.lower() == "content-type" for name in headers):
        headers["content-type"] = f"{kind}; charset=utf-8"
    out: dict[str, Any] = {
        "method": method,
        "path": form["path"],
        "query": [list(pair) for pair in _active_rows(form["query"])],
        "headers": headers,
        "body": body,
    }
    if form["auth"].get("type") != "none":
        out["auth"] = form["auth"]
    return out


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
