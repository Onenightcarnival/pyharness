"""Failure codes of a model call: one stable code per failure, read from the exception a provider raised.

| code                        | failure                                                              |
|-----------------------------|----------------------------------------------------------------------|
| ``RATE_LIMIT``              | HTTP 429                                                             |
| ``SERVER``                  | HTTP 5xx other than 504                                              |
| ``TIMEOUT``                 | a request or stream timeout; HTTP 408 and 504                        |
| ``TRANSPORT``               | the connection could not be made or broke                            |
| ``STREAM_CLOSED``           | the response stream ended early or broke the protocol                |
| ``EMPTY_RESPONSE``          | the provider answered without content                                |
| ``AUTH``                    | HTTP 401 and 403                                                     |
| ``CONTEXT_WINDOW_EXCEEDED`` | HTTP 400 whose message names the context window                      |
| ``CONFIG``                  | the route is not usable: no model, no credential, unknown provider   |
| ``HTTP_<status>``           | any other HTTP error status                                          |
| ``UNKNOWN``                 | nothing above                                                        |

| name                 | contract                                                                    |
|----------------------|-----------------------------------------------------------------------------|
| ``failure_code()``   | the code of an exception; a ``code`` attribute in this vocabulary wins, then the HTTP status, |
|                      | then the exception type; the cause chain is followed                        |
| ``retry_after_ms()`` | the wait a provider asked for: ``retry_after_ms`` of the exception, else its ``Retry-After`` |
|                      | response header in seconds; ``None`` without one                            |
| ``TRANSIENT_CODES``  | codes a retry policy retries by default                                     |
| ``RETRY_CHOICES``    | codes a settings form offers for a retry policy                             |
| ``CONTINUABLE_CODES``| codes after which a failed turn may be continued by hand                    |
"""

from __future__ import annotations

import re

import httpx

from pyharness import package_toml

_CFG = package_toml(__file__)["failures"]
TRANSIENT_CODES: tuple[str, ...] = tuple(_CFG["TRANSIENT_CODES"])
RETRY_CHOICES: tuple[str, ...] = tuple(_CFG["RETRY_CHOICES"])
CONTINUABLE_CODES: tuple[str, ...] = tuple(_CFG["CONTINUABLE_CODES"])
CODE = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")
CONTEXT_WINDOW = re.compile(r"context[ _-]?(window|length)|too many tokens|maximum context", re.IGNORECASE)
CHAIN_DEPTH = 6


def _status(error: BaseException) -> int | None:
    response = getattr(error, "response", None)
    for value in (
        getattr(error, "status_code", None),
        getattr(response, "status_code", None),
        getattr(error, "code", None),
    ):
        if isinstance(value, int) and not isinstance(value, bool) and 400 <= value <= 599:
            return value
    return None


def _from_status(status: int, message: str) -> str:
    if status in (401, 403):
        return "AUTH"
    if status == 429:
        return "RATE_LIMIT"
    if status in (408, 504):
        return "TIMEOUT"
    if status >= 500:
        return "SERVER"
    if status == 400 and CONTEXT_WINDOW.search(message):
        return "CONTEXT_WINDOW_EXCEEDED"
    return f"HTTP_{status}"


def _from_type(error: BaseException) -> str | None:
    name = type(error).__name__
    if isinstance(error, TimeoutError | httpx.TimeoutException) or "Timeout" in name:
        return "TIMEOUT"
    if isinstance(error, httpx.RemoteProtocolError | httpx.DecodingError) or "IncompleteRead" in name:
        return "STREAM_CLOSED"
    if isinstance(error, httpx.TransportError | ConnectionError) or "ConnectionError" in name:
        return "TRANSPORT"
    return None


def _chain(error: BaseException) -> list[BaseException]:
    out: list[BaseException] = []
    current: BaseException | None = error
    while current is not None and len(out) < CHAIN_DEPTH:
        out.append(current)
        current = current.__cause__ or current.__context__
    return out


def retry_after_ms(error: BaseException) -> int | None:
    for current in _chain(error):
        given = getattr(current, "retry_after_ms", None)
        if isinstance(given, int | float) and not isinstance(given, bool) and given >= 0:
            return int(given)
        headers = getattr(getattr(current, "response", None), "headers", None)
        value = headers.get("retry-after") if headers is not None and hasattr(headers, "get") else None
        if isinstance(value, str) and value.strip().replace(".", "", 1).isdigit():
            return int(float(value) * 1000)
    return None


def failure_code(error: BaseException) -> str:
    for current in _chain(error):
        code = getattr(current, "code", None)
        if isinstance(code, str) and CODE.match(code):
            return code
        status = _status(current)
        found = _from_status(status, str(current)) if status is not None else _from_type(current)
        if found is not None:
            return found
    return "UNKNOWN"
