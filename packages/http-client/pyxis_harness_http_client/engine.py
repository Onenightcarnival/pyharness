from __future__ import annotations

import asyncio
import base64
import codecs
import contextlib
import ipaddress
import re
import secrets as token
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

import httpx

from pyxis_harness import package_toml

from .capture import run_captures
from .protocol import (
    DEFAULT_TIMEOUT_MS,
    DIRECT_TARGET_ID,
    HISTORY_BODY_BYTES,
    PANEL_BODY_BYTES,
    VARIABLE_NAME,
    Pairs,
    SseParser,
    is_event_stream,
    is_method,
    join_url,
    referenced_variables,
    request_input_of,
    saved_request_title,
    substitute,
)
from .store import (
    FORBIDDEN_HEADERS,
    HistoryStore,
    RequestStore,
    StoreError,
    TargetStore,
    ValueStore,
    auth_missing,
    missing_secrets,
    normalize_request_auth,
    secrets_of,
    usable_request_auth,
)

_CFG = package_toml(__file__)["engine"]
MAX_REDIRECTS: int = _CFG["MAX_REDIRECTS"]
MAX_REFRESH_DEPTH: int = _CFG["MAX_REFRESH_DEPTH"]
REFRESH_SKEW_MS: int = _CFG["REFRESH_SKEW_MS"]
REQUEST_BODY_BYTES: int = _CFG["REQUEST_BODY_BYTES"]
MASK: str = _CFG["MASK"]
USER_AGENT: str = _CFG["USER_AGENT"]
CREDENTIAL_HEADERS: frozenset[str] = frozenset(_CFG["CREDENTIAL_HEADERS"])

REDIRECT_STATUSES = (301, 302, 303, 307, 308)
REQUEST_ID = re.compile(r"^[0-9a-f]{1,64}$")
LINE_BREAK = re.compile(r"[\r\n]")
CHARSET = re.compile(r"charset\s*=\s*\"?([^\";\s]+)", re.IGNORECASE)
TEXT_TYPES = re.compile(
    r"^(text/|application/(json|xml|javascript|ecmascript|x-www-form-urlencoded|x-ndjson|ld\+json|problem\+json"
    r"|graphql|yaml|x-yaml|toml|sql|xhtml\+xml)|image/svg\+xml|message/)",
    re.IGNORECASE,
)
STRUCTURED_SUFFIX = re.compile(r"\+(json|xml)$", re.IGNORECASE)
BINARY_TYPES = re.compile(
    r"^((image|audio|video|font)/|application/(octet-stream|zip|gzip|pdf|x-tar|wasm|x-protobuf|protobuf|msgpack"
    r"|x-msgpack))",
    re.IGNORECASE,
)
DIRECT_TARGET: dict[str, Any] = {
    "id": DIRECT_TARGET_ID,
    "name": "",
    "baseUrl": "",
    "auth": {"type": "none"},
    "headers": {},
    "variables": {},
    "secrets": {},
    "allowedHosts": [],
    "allowMutations": True,
    "allowPrivate": True,
    "timeoutMs": DEFAULT_TIMEOUT_MS,
    "createdAt": 0,
    "updatedAt": 0,
}
PRIVATE_HINT = 'enable "allow private network" on the target'
# Fields of an auth setting in which ``{{variables}}`` are substituted, by type.
AUTH_TEXTS = {"bearer": ("token",), "basic": ("username", "password"), "header": ("value",), "query": ("value",)}
NO_AUTH: dict[str, Any] = {"type": "none"}
# Reads the response as received: status, headers, decoded body, whether the body was cut. Returns the values to mask.
CaptureHook = Callable[[int, httpx.Headers, str, bool], list[str]]


class PolicyError(ValueError):
    """The request is malformed, addresses an unknown target, or is refused by the target's host policy."""


class _Cancelled(Exception):
    """The caller stopped the request."""


class _Expired(Exception):
    """The target's timeout passed."""


@dataclass
class SendOptions:
    """
    ``cancel``: set to stop the request (the exchange carries the error ``cancelled``; an event stream ends with
    what arrived). ``on_stream_start(head)`` and ``on_stream_event(event, at_ms)`` report an event stream as it
    arrives.
    """

    source: str  # "panel" or "agent"
    max_body_bytes: int = PANEL_BODY_BYTES
    record: bool = True
    cancel: asyncio.Event | None = None
    keep_binary: bool = False
    on_stream_start: Callable[[dict[str, Any]], None] | None = None
    on_stream_event: Callable[[dict[str, Any], int], None] | None = None


@dataclass
class _Refreshing:
    """
    A send the host makes by itself to renew variables. ``chain``: saved requests being refreshed, outermost first;
    the last one is the request being sent. ``variables``: the variables the refresh is sent for.
    """

    chain: list[str]
    variables: list[str]


@dataclass
class _RefreshGroup:
    """One saved request to send as a refresh, the variables wanted from it, and why."""

    request: dict[str, Any]
    variables: list[str]
    reason: str  # "missing", "expired" or "rejected"


class _Deadline:
    """Runs awaitables until the timeout passes or ``cancel`` is set; ``touch()`` restarts the timeout."""

    def __init__(self, seconds: float, cancel: asyncio.Event | None) -> None:
        self.seconds = seconds
        self.cancel = cancel
        self.expires = time.monotonic() + seconds

    def touch(self) -> None:
        self.expires = time.monotonic() + self.seconds

    async def run(self, awaitable: Awaitable[Any]) -> Any:
        work = asyncio.ensure_future(awaitable)
        stop = asyncio.ensure_future(self.cancel.wait()) if self.cancel is not None else None
        try:
            await asyncio.wait(
                {work, stop} if stop else {work},
                timeout=max(0.0, self.expires - time.monotonic()),
                return_when=asyncio.FIRST_COMPLETED,
            )
        finally:
            if stop is not None:
                stop.cancel()
            if not work.done():
                work.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await work
        if work.cancelled():
            raise _Cancelled if self.cancel is not None and self.cancel.is_set() else _Expired
        return work.result()


def now_ms() -> int:
    return int(time.time() * 1000)


async def _settled(flight: asyncio.Future[Any], cancel: asyncio.Event | None) -> Any:
    """The flight's result; :class:`_Cancelled` once ``cancel`` is set or the flight is stopped. The flight runs on."""
    stop = asyncio.ensure_future(cancel.wait()) if cancel is not None else None
    try:
        await asyncio.wait({flight, stop} if stop else {flight}, return_when=asyncio.FIRST_COMPLETED)
    finally:
        if stop is not None:
            stop.cancel()
    if not flight.done() or flight.cancelled():
        raise _Cancelled
    return flight.result()


# ---------------------------------------------------------------------- variables
def auth_texts(auth: Mapping[str, Any]) -> list[str]:
    """Texts of an auth setting in which ``{{variables}}`` are substituted."""
    return [auth[field] for field in AUTH_TEXTS.get(auth["type"], ())]


def substitute_auth(auth: Mapping[str, Any], variables: Mapping[str, str]) -> dict[str, Any]:
    return {**auth, **{field: substitute(auth[field], variables) for field in AUTH_TEXTS.get(auth["type"], ())}}


def is_expired(entry: Mapping[str, Any], now: int | None = None) -> bool:
    """
    Whether a captured value has reached its expiry: :data:`REFRESH_SKEW_MS` early, or a tenth of its lifetime
    early when that is shorter.
    """
    expires = entry.get("expiresAt")
    if expires is None:
        return False
    skew = min(REFRESH_SKEW_MS, max(0, expires - entry["at"]) / 10)
    return (now_ms() if now is None else now) >= expires - skew


def refresh_failure(refresh: Mapping[str, Any]) -> str:
    """Error of a request that is not sent because a refresh it needs failed."""
    names = ", ".join(f"{{{{{name}}}}}" for name in refresh["variables"])
    return f"refresh of {names} by request '{refresh['requestName']}' failed: {refresh.get('error') or 'unknown error'}"


# ---------------------------------------------------------------------- policy
def host_matches(hostname: str, pattern: str) -> bool:
    """``hostname`` equals the pattern, or is a subdomain of a ``*.domain`` pattern."""
    host, want = hostname.lower().removesuffix("."), pattern.lower()
    if want.startswith("*."):
        return host.endswith(want[1:]) and len(host) > len(want) - 1
    return host == want


def _allowed(url: httpx.URL, target: Mapping[str, Any]) -> bool:
    if target["id"] == DIRECT_TARGET_ID or url.host == httpx.URL(target["baseUrl"]).host:
        return True
    return any(host_matches(url.host, pattern.strip("[]")) for pattern in target["allowedHosts"])


def _private_v4(address: ipaddress.IPv4Address) -> bool:
    a, b = address.packed[0], address.packed[1]
    return (
        a in (0, 10, 127)
        or a >= 224
        or (a == 100 and 64 <= b <= 127)
        or (a == 169 and b == 254)
        or (a == 172 and 16 <= b <= 31)
        or (a == 192 and b == 168)
    )


def is_private_address(address: str) -> bool:
    """Loopback, link-local, unique-local, unspecified, multicast and RFC 1918 ranges."""
    try:
        parsed = ipaddress.ip_address(address.strip("[]").split("%")[0])
    except ValueError:
        return False
    if isinstance(parsed, ipaddress.IPv4Address):
        return _private_v4(parsed)
    if parsed.ipv4_mapped is not None:
        return _private_v4(parsed.ipv4_mapped)
    first = int.from_bytes(parsed.packed[:2])
    return int(parsed) in (0, 1) or first & 0xFE00 == 0xFC00 or first & 0xFFC0 == 0xFE80 or first & 0xFF00 == 0xFF00


async def assert_public(url: httpx.URL) -> None:
    """Literal addresses are checked directly; a name is resolved and every address must be public."""
    host = url.host
    if host == "localhost" or host.endswith(".localhost"):
        raise PolicyError(f"host '{host}' is a loopback name; {PRIVATE_HINT}")
    try:
        ipaddress.ip_address(host)
    except ValueError:
        try:
            found = await asyncio.get_running_loop().getaddrinfo(host, None)
        except OSError as exc:
            raise PolicyError(f"cannot resolve '{host}': {exc}") from exc
        hit = next((info[4][0] for info in found if is_private_address(str(info[4][0]))), None)
        if hit is not None:
            raise PolicyError(f"host '{host}' resolves to the private address {hit}; {PRIVATE_HINT}") from None
        return
    if is_private_address(host):
        raise PolicyError(f"address '{host}' is private; {PRIVATE_HINT}")


def build_url(target: Mapping[str, Any], path: str, query: Any) -> httpx.URL:
    try:
        return join_url(target["baseUrl"], path, query)
    except ValueError as exc:
        raise PolicyError(str(exc)) from exc


# ---------------------------------------------------------------------- masking and bodies
def typed_credentials(headers: Mapping[str, str]) -> list[str]:
    """Credentials typed into request headers: the value, or the part after the scheme word (``Bearer …``)."""
    out = []
    for name, value in headers.items():
        if name.lower() not in CREDENTIAL_HEADERS:
            continue
        scheme, space, rest = value.partition(" ")
        out.append(rest.strip() if name.lower() != "cookie" and scheme and space else value)
    return out


def mask_secrets(text: str, secrets: list[str]) -> str:
    """Replace every secret of three characters or more, longest first, and its URL-encoded form."""
    for secret in sorted((s for s in secrets if len(s) >= 3), key=len, reverse=True):
        text = text.replace(secret, MASK)
        encoded = quote(secret, safe="-_.!~*'()")
        if encoded != secret:
            text = text.replace(encoded, MASK)
    return text


def is_textual(content_type: str, sample: bytes) -> bool:
    """Textual by media type, or by the absence of NUL bytes in the first KiB."""
    kind = content_type.split(";", maxsplit=1)[0].strip()
    if kind:
        if TEXT_TYPES.match(kind) or STRUCTURED_SUFFIX.search(kind):
            return True
        if BINARY_TYPES.match(kind):
            return False
    return b"\0" not in sample[:1024]


def _decode(data: bytes, content_type: str) -> str:
    match = CHARSET.search(content_type)
    try:
        return data.decode(match.group(1).lower() if match else "utf-8", errors="replace")
    except LookupError:
        return data.decode("utf-8", errors="replace")


def truncate(text: str, limit: int) -> tuple[str, bool]:
    """``text`` cut to ``limit`` UTF-8 bytes on a character boundary, and whether it was cut."""
    data = text.encode()
    return (text, False) if len(data) <= limit else (data[:limit].decode(errors="ignore"), True)


def _masked(headers: httpx.Headers, secrets: list[str]) -> dict[str, str]:
    return {name: mask_secrets(value, secrets) for name, value in headers.items()}


def _head(response: httpx.Response, content_type: str, secrets: list[str]) -> dict[str, Any]:
    """Status line and headers of a response, masked."""
    return {
        "status": response.status_code,
        "statusText": response.reason_phrase,
        "headers": _masked(response.headers, secrets),
        "contentType": content_type,
    }


def human_bytes(size: int) -> str:
    if size < 1024:
        return f"{size} B"
    value, units = size / 1024, ["KiB", "MiB", "GiB"]
    while value >= 1024 and len(units) > 1:
        value, units = value / 1024, units[1:]
    return f"{value:.0f} {units[0]}" if value >= 100 else f"{value:.1f} {units[0]}"


def for_history(exchange: dict[str, Any]) -> dict[str, Any]:
    """History copy of an exchange: bodies capped at :data:`HISTORY_BODY_BYTES`, binary bodies dropped."""
    request = dict(exchange["request"])
    request["body"], cut = truncate(request["body"], HISTORY_BODY_BYTES)
    request["bodyTruncated"] = request["bodyTruncated"] or cut
    stored = {**exchange, "request": request}
    if exchange.get("response") is not None:
        response = {k: v for k, v in exchange["response"].items() if k != "bodyBase64"}
        response["body"], cut = truncate(response["body"], HISTORY_BODY_BYTES)
        response["bodyTruncated"] = response["bodyTruncated"] or cut
        stored["response"] = response
    return stored


# ---------------------------------------------------------------------- input
def _query_pairs(raw: Any) -> Pairs:
    wrong = "query must be an object of strings or a list of [name, value] pairs"
    if raw is None:
        return []
    if isinstance(raw, list):
        for item in raw:
            if not isinstance(item, list | tuple) or len(item) != 2 or not all(isinstance(x, str) for x in item):
                raise PolicyError(wrong)
        items = [(name, value) for name, value in raw]
    elif isinstance(raw, dict):
        for name, value in raw.items():
            if not isinstance(value, str):
                raise PolicyError(f"query.{name} must be a string")
        items = list(raw.items())
    else:
        raise PolicyError(wrong)
    return [(str(name).strip(), value) for name, value in items if str(name).strip()]


def validate_input(raw: Any) -> dict[str, Any]:
    """The composed request with its shape checked: method, path, query pairs, headers, body, request id, auth."""
    if not isinstance(raw, dict):
        raise PolicyError("request must be an object")
    method = raw["method"].upper() if isinstance(raw.get("method"), str) else "GET"
    if not is_method(method):
        raise PolicyError(f"unsupported method '{raw.get('method')}'")
    headers = raw.get("headers")
    if headers is not None and not isinstance(headers, dict):
        raise PolicyError("headers must be an object of strings")
    for name, value in (headers or {}).items():
        if not isinstance(value, str):
            raise PolicyError(f"headers.{name} must be a string")
        if LINE_BREAK.search(value):
            raise PolicyError(f"header {name} must not contain line breaks")
    if raw.get("body") is not None and not isinstance(raw["body"], str):
        raise PolicyError("body must be a string")
    request_id = raw.get("requestId")
    auth = None
    if raw.get("auth") is not None:
        try:
            auth = normalize_request_auth(raw["auth"])
        except StoreError as exc:
            raise PolicyError(str(exc)) from exc
    return {
        "method": method,
        "path": raw["path"].strip() if isinstance(raw.get("path"), str) else "",
        "query": _query_pairs(raw.get("query")),
        "headers": {str(name).strip(): value for name, value in (headers or {}).items() if str(name).strip()},
        "body": raw.get("body"),
        "requestId": request_id if isinstance(request_id, str) and REQUEST_ID.match(request_id) else None,
        "auth": auth,
    }


def _apply_auth(auth: Mapping[str, Any], headers: httpx.Headers, url: httpx.URL) -> httpx.URL:
    """Inject the auth into the headers, or into the URL it returns."""
    kind = auth["type"]
    if kind == "bearer":
        headers["authorization"] = f"Bearer {auth['token']}"
    elif kind == "basic":
        pair = f"{auth['username']}:{auth['password']}".encode()
        headers["authorization"] = f"Basic {base64.b64encode(pair).decode()}"
    elif kind == "header":
        headers[auth["name"]] = auth["value"]
    elif kind == "query":
        return url.copy_set_param(auth["name"], auth["value"])
    return url


def _origin(url: httpx.URL) -> tuple[str, str, int | None]:
    return url.scheme, url.host, url.port


# ---------------------------------------------------------------------- engine
class HttpEngine:
    """
    ``transport`` replaces the HTTP transport (tests). ``requests``: saved requests, the source of capture rules and
    of refreshes. ``values``: captured variable values. Without both, nothing is captured, refreshed or substituted
    from captured values.
    """

    def __init__(
        self,
        store: TargetStore,
        history: HistoryStore,
        transport: Any = None,
        requests: RequestStore | None = None,
        values: ValueStore | None = None,
    ) -> None:
        self.store = store
        self.history = history
        self.requests = requests
        self.values = values
        self.client = httpx.AsyncClient(
            follow_redirects=False,
            timeout=None,
            transport=transport,
            headers={"user-agent": USER_AGENT},
            trust_env=False,
        )
        # Refreshes in flight by scope and saved request; concurrent requests wait for the same one.
        self._refreshing: dict[tuple[str, str], asyncio.Task[dict[str, Any]]] = {}
        self._flights: set[asyncio.Task[dict[str, Any]]] = set()

    async def aclose(self) -> None:
        flights = list(self._flights)
        for flight in flights:
            flight.cancel()
        await asyncio.gather(*flights, return_exceptions=True)
        await self.client.aclose()

    def target(self, ref: str) -> dict[str, Any]:
        """Resolve a target by id or name; raises :class:`PolicyError`."""
        target = self.store.find(ref)
        if target is None:
            raise PolicyError(f"target '{ref}' not found (see the HTTP page)")
        return target

    async def send(self, ref: str, raw: Any, options: SendOptions) -> dict[str, Any]:
        """
        Send a request and record it, after refreshing the variables it references whose value is missing or
        expired; returns the exchange. Policy and transport failures, a failed refresh included, are its ``error``.
        """
        return await self._run(ref, raw, options, None)

    async def _run(self, ref: str, raw: Any, options: SendOptions, context: _Refreshing | None) -> dict[str, Any]:
        direct = ref == DIRECT_TARGET_ID and options.source == "panel"
        target = DIRECT_TARGET if direct else self.target(ref)
        request = validate_input(raw)
        # A form the user wrote: the page's send, or a saved request the host sends as a refresh.
        authored = options.source == "panel" or context is not None
        chain = context.chain if context is not None else []
        refreshed: list[dict[str, Any]] = []
        blocked: str | None = None
        for group in self._refresh_groups(target, request, authored, rejected=False):
            outcome = await self._refresh(target, group, options, chain)
            refreshed.append(outcome)
            if not outcome["ok"]:
                blocked = refresh_failure(outcome)
                break
        exchange = await self._exchange(target, request, options, context, refreshed, blocked)
        # A 401 renews the variables whose rule asks for it, then the request is sent once more.
        response = exchange.get("response")
        stopped = options.cancel is not None and options.cancel.is_set()
        if blocked is not None or response is None or response["status"] != 401 or "stream" in response or stopped:
            return exchange
        done = {outcome["requestId"] for outcome in refreshed}
        again = [
            group
            for group in self._refresh_groups(target, request, authored, rejected=True)
            if group.request["id"] not in done
        ]
        if not again:
            return exchange
        for group in again:
            outcome = await self._refresh(target, group, options, chain)
            refreshed.append(outcome)
            if not outcome["ok"]:
                return {**exchange, "refreshed": list(refreshed)}
        return await self._exchange(target, request, options, context, refreshed, None)

    # ------------------------------------------------------------------ what a request carries
    def _saved_of(self, target: Mapping[str, Any], request: Mapping[str, Any], authored: bool) -> dict[str, Any] | None:
        """The saved request behind a send, when the send is the user's form and the request belongs to the scope."""
        if not authored or request["requestId"] is None or self.requests is None or self.values is None:
            return None
        saved = self.requests.get(request["requestId"])
        return saved if saved is not None and saved["targetId"] == target["id"] else None

    def _applied(
        self, target: Mapping[str, Any], request: Mapping[str, Any], authored: bool
    ) -> tuple[dict[str, Any], dict[str, str]]:
        """
        The auth and the fixed headers the target adds to a request, before substitution. A request that captures
        a variable is sent without the target auth and the fixed headers that reference that variable. The form's
        own auth applies when the user wrote the form and no target auth does.
        """
        saved = self._saved_of(target, request, authored)
        produced = {rule["name"].strip() for rule in (saved or {}).get("captures", []) if rule["enabled"]}

        def own(texts: list[str]) -> bool:
            return not produced.isdisjoint(referenced_variables(texts))

        auth = NO_AUTH if own(auth_texts(target["auth"])) else target["auth"]
        if authored and auth["type"] == "none":
            auth = usable_request_auth(request["auth"]) or auth
        return auth, {name: value for name, value in target["headers"].items() if not own([value])}

    def _references(self, target: Mapping[str, Any], request: Mapping[str, Any], authored: bool) -> set[str]:
        """
        Variable names a request references: in its path, query, headers and body, and in the target's fixed
        headers and auth sent with it.
        """
        auth, fixed = self._applied(target, request, authored)
        sends_body = request["body"] is not None and request["method"] not in ("GET", "HEAD")
        return referenced_variables(
            [
                request["path"],
                *(text for pair in request["query"] for text in pair),
                *request["headers"].values(),
                request["body"] if sends_body else "",
                *fixed.values(),
                *auth_texts(auth),
            ]
        )

    # ------------------------------------------------------------------ refresh
    def _refresh_groups(
        self, target: Mapping[str, Any], request: Mapping[str, Any], authored: bool, rejected: bool
    ) -> list[_RefreshGroup]:
        """
        Saved requests to send for a request, grouped by request in creation order. Before the request: the
        referenced variables with a refresh rule whose value is missing or expired. ``rejected``, after a 401:
        those whose rule renews on a 401. The request being sent never refreshes itself.
        """
        if self.requests is None or self.values is None:
            return []
        names = self._references(target, request, authored)
        scope = target["id"]
        entries = {name: self.values.entry(scope, name) for name in names}
        sources: dict[str, tuple[dict[str, Any], dict[str, Any]]] = {}
        for saved in self.requests.list(scope) if names else []:
            for rule in saved["captures"]:
                name = rule["name"].strip()
                renews = rule["enabled"] and rule["refresh"] != "off" and VARIABLE_NAME.match(name)
                if not renews or name not in names:
                    continue
                # Of several requests that renew a variable, the one its value came from is sent.
                if name not in sources or (entries[name] or {}).get("requestId") == saved["id"]:
                    sources[name] = (saved, rule)
        groups: dict[str, _RefreshGroup] = {}
        for name, (saved, rule) in sources.items():
            if authored and request["requestId"] == saved["id"]:
                continue
            entry = entries[name]
            if rejected:
                reason = "rejected" if rule["refresh"] == "rejected" else None
            elif entry is None:
                reason = "missing"
            else:
                reason = "expired" if is_expired(entry) else None
            if reason is None:
                continue
            if saved["id"] in groups:
                groups[saved["id"]].variables.append(name)
            else:
                groups[saved["id"]] = _RefreshGroup(saved, [name], reason)
        return list(groups.values())

    def _fly(self, scope: str, saved: Mapping[str, Any], source: str, context: _Refreshing) -> asyncio.Task[Any]:
        """Send a saved request as stored, on its own task: it completes whoever waits for it."""
        raw = {**request_input_of(saved), "requestId": saved["id"]}
        flight = asyncio.ensure_future(self._run(scope, raw, SendOptions(source=source), context))
        self._flights.add(flight)
        flight.add_done_callback(self._landed)
        return flight

    def _landed(self, flight: asyncio.Task[Any]) -> None:
        self._flights.discard(flight)
        if not flight.cancelled():
            flight.exception()  # read here: a waiter that left never reads it

    async def _refresh(
        self, target: Mapping[str, Any], group: _RefreshGroup, options: SendOptions, chain: list[str]
    ) -> dict[str, Any]:
        """Send a saved request as a refresh; the outcome tells whether it renewed the wanted variables."""
        saved, variables = group.request, group.variables
        outcome: dict[str, Any] = {
            "requestId": saved["id"],
            "requestName": saved_request_title(saved),
            "variables": variables,
            "reason": group.reason,
        }
        if saved["id"] in chain:
            return {**outcome, "ok": False, "error": "the request depends on a variable it refreshes"}
        if len(chain) >= MAX_REFRESH_DEPTH:
            return {**outcome, "ok": False, "error": f"more than {MAX_REFRESH_DEPTH} refreshes in a chain"}
        context = _Refreshing([*chain, saved["id"]], variables)
        # Requests that need the same refresh wait for one send; a refresh within a refresh is its own send.
        key = (target["id"], saved["id"])
        if chain:
            flight = self._fly(target["id"], saved, options.source, context)
        elif key in self._refreshing:
            flight = self._refreshing[key]
        else:
            flight = self._refreshing[key] = self._fly(target["id"], saved, options.source, context)
            flight.add_done_callback(lambda _: self._refreshing.pop(key, None))
        try:
            exchange = await _settled(flight, options.cancel)
        except _Cancelled:
            return {**outcome, "ok": False, "error": "cancelled"}
        except PolicyError as exc:
            return {**outcome, "ok": False, "error": str(exc)}
        outcome["exchangeId"] = exchange["id"]
        if "error" in exchange:
            return {**outcome, "ok": False, "error": exchange["error"]}
        for name in variables:
            result = next((item for item in exchange.get("captures", []) if item["name"] == name), None)
            if result is None or not result["ok"]:
                why = (result or {}).get("error") or "no capture rule ran"
                return {**outcome, "ok": False, "error": f"{{{{{name}}}}} was not captured: {why}"}
        return {**outcome, "ok": True}

    # ------------------------------------------------------------------ one request
    async def _exchange(
        self,
        target: Mapping[str, Any],
        request: Mapping[str, Any],
        options: SendOptions,
        context: _Refreshing | None,
        refreshed: list[dict[str, Any]],
        blocked: str | None,
    ) -> dict[str, Any]:
        """Send one request and record it. ``blocked`` records the exchange with that error instead of sending."""
        authored = options.source == "panel" or context is not None
        # Captured values are variables of the scope; one named like a target variable takes its place.
        captured = self.values.map(target["id"]) if self.values is not None else {}
        filled = {name: value for name, value in target["secrets"].items() if value}
        variables = {**target["variables"], **filled, **captured}
        # The target as this request is sent to it: auth and fixed headers with their variables in place.
        applied_auth, applied_headers = self._applied(target, request, authored)
        auth = substitute_auth(applied_auth, variables)
        fixed = {name: substitute(value, variables) for name, value in applied_headers.items()}
        # The user's saved request brings the capture rules; they run on a response of its own scope.
        saved = self._saved_of(target, request, authored)
        rules = [rule for rule in (saved or {}).get("captures", []) if rule["enabled"] and rule["name"].strip()]
        path = substitute(request["path"], variables)
        query = [(substitute(k, variables), substitute(v, variables)) for k, v in request["query"]]
        headers = {name: substitute(value, variables) for name, value in request["headers"].items()}
        # An auth value whose variable has no value is the reference as written, not a secret.
        configured = [secret for secret in (*secrets_of(auth), *filled.values()) if not referenced_variables([secret])]
        secrets = [*configured, *typed_credentials(headers), *captured.values()]
        raw_body = request["body"] or ""
        body = substitute(raw_body, variables) if raw_body and request["method"] not in ("GET", "HEAD") else None
        stored_body, cut = truncate(mask_secrets(raw_body, secrets), REQUEST_BODY_BYTES)
        exchange: dict[str, Any] = {
            "id": token.token_hex(6),
            "at": now_ms(),
            "targetId": target["id"],
            "targetName": target["name"],
            "source": options.source,
            **({"requestId": request["requestId"]} if request["requestId"] else {}),
            "request": {
                "method": request["method"],
                "url": "",
                "path": request["path"],
                "query": [[k, mask_secrets(v, secrets)] for k, v in request["query"]],
                "headers": {k: mask_secrets(v, secrets) for k, v in request["headers"].items()},
                "body": stored_body,
                "bodyTruncated": cut,
            },
            **({"refreshed": list(refreshed)} if refreshed else {}),
            **({"refreshOf": list(context.variables)} if context is not None else {}),
        }

        def capture(status: int, received: httpx.Headers, text: str, truncated: bool) -> list[str]:
            values, lifetimes, exchange["captures"] = run_captures(rules, status, received, text, truncated)
            if self.values is not None and saved is not None:
                self.values.set(target["id"], values, saved["id"], lifetimes)
            return list(values.values())

        started = time.monotonic()
        try:
            if blocked is not None:
                raise PolicyError(blocked)
            referenced = self._references(target, request, authored)
            unfilled = [name for name in missing_secrets(target) if name in referenced]
            if unfilled:
                names = ", ".join(f"{{{{{name}}}}}" for name in unfilled)
                raise PolicyError(
                    f"secret variable {names} of target '{target['name']}' is not filled in (edit the target on the "
                    "HTTP page)"
                )
            url = build_url(target, path, query)
            if not _allowed(url, target):
                raise PolicyError(
                    f"host '{url.host}' is not allowed for target '{target['name']}' (add it to allowed hosts)"
                )
            sent = httpx.Headers()
            for source in (fixed, headers):
                for name, value in source.items():
                    if name.lower() not in FORBIDDEN_HEADERS:
                        sent[name] = value
            if body is not None and "content-type" not in sent:
                structured = body.lstrip().startswith(("{", "["))
                sent["content-type"] = f"{'application/json' if structured else 'text/plain'}; charset=utf-8"
            sent.setdefault("accept", "*/*")
            if auth_missing(target["auth"]):
                raise PolicyError(
                    f"authentication of target '{target['name']}' is not filled in (edit the target on the HTTP page)"
                )
            url = _apply_auth(auth, sent, url)
            exchange["request"]["url"] = mask_secrets(str(url), secrets)
            exchange["request"]["sentHeaders"] = _masked(sent, secrets)
            exchange["response"] = await self._perform(
                target, auth, url, request["method"], sent, body, secrets, started, options, capture if rules else None
            )
            if rules and "captures" not in exchange:
                missed = "event streams are not captured"
                exchange["captures"] = [{"name": rule["name"].strip(), "ok": False, "error": missed} for rule in rules]
        except _Cancelled:
            exchange["error"] = "cancelled"
        except _Expired:
            exchange["error"] = f"timed out after {target['timeoutMs']} ms"
        except (PolicyError, httpx.HTTPError) as exc:
            stopped = options.cancel is not None and options.cancel.is_set()
            exchange["error"] = "cancelled" if stopped else mask_secrets(str(exc) or type(exc).__name__, secrets)
        if options.record:
            self.history.add(for_history(exchange))
        return exchange

    async def test(self, ref: str) -> dict[str, Any]:
        """``GET`` the base URL with auth; any HTTP status counts as reachable."""
        started = time.monotonic()
        exchange = await self.send(
            ref, {"method": "GET", "path": ""}, SendOptions(source="panel", max_body_bytes=0, record=False)
        )
        latency = int((time.monotonic() - started) * 1000)
        if "error" in exchange:
            return {"ok": False, "latencyMs": latency, "error": exchange["error"]}
        return {"ok": True, "status": exchange["response"]["status"], "latencyMs": latency}

    async def _perform(
        self,
        target: Mapping[str, Any],
        auth: Mapping[str, Any],
        url: httpx.URL,
        method: str,
        headers: httpx.Headers,
        body: str | None,
        secrets: list[str],
        started: float,
        options: SendOptions,
        capture: CaptureHook | None = None,
    ) -> dict[str, Any]:
        deadline = _Deadline(target["timeoutMs"] / 1000, options.cancel)
        if options.cancel is not None and options.cancel.is_set():
            raise _Cancelled
        redirects: list[str] = []
        hop = 0
        while True:
            if not target["allowPrivate"]:
                await deadline.run(assert_public(url))
            content = body.encode() if body is not None else None
            request = self.client.build_request(method, url, headers=headers, content=content)
            response = await deadline.run(self.client.send(request, stream=True))
            try:
                location = response.headers.get("location")
                if location is None or response.status_code not in REDIRECT_STATUSES or hop >= MAX_REDIRECTS:
                    return await self._read(response, secrets, started, redirects, deadline, options, capture)
                try:
                    following = url.join(location)
                except (httpx.InvalidURL, ValueError) as exc:
                    raise PolicyError(f"invalid redirect location '{location}'") from exc
                if following.scheme not in ("http", "https"):
                    raise PolicyError(f"redirect to unsupported scheme '{following.scheme}:'")
                if not _allowed(following, target):
                    name = target["name"]
                    raise PolicyError(
                        f"redirect to '{following.host}' is not allowed for target '{name}' (add it to allowed hosts)"
                    )
                if _origin(following) != _origin(url):
                    # Credentials never travel to another origin.
                    dropped = ["authorization", "cookie", *([auth["name"]] if auth["type"] == "header" else [])]
                    for name in dropped:
                        headers.pop(name, None)
                    if auth["type"] == "query":
                        params = [(k, v) for k, v in following.params.multi_items() if k != auth["name"]]
                        following = following.copy_with(params=params or None)
                if response.status_code == 303 or (response.status_code in (301, 302) and method == "POST"):
                    method, body = "GET", None
                    headers.pop("content-type", None)
                redirects.append(mask_secrets(str(following), secrets))
                url, hop = following, hop + 1
            finally:
                await response.aclose()

    async def _read(
        self,
        response: httpx.Response,
        secrets: list[str],
        started: float,
        redirects: list[str],
        deadline: _Deadline,
        options: SendOptions,
        capture: CaptureHook | None,
    ) -> dict[str, Any]:
        """The exchange response of the final HTTP response."""
        content_type = response.headers.get("content-type", "")
        chunks = response.aiter_bytes()
        limit = options.max_body_bytes
        if is_event_stream(content_type):
            head = _head(response, content_type, secrets)
            return await self._read_stream(chunks, head, secrets, started, redirects, deadline, options)
        data, truncated = bytearray(), False
        while limit > 0:
            chunk = await deadline.run(anext(chunks, None))
            if chunk is None:
                break
            data += chunk
            if len(data) > limit:
                del data[limit:]
                truncated = True
                break
        textual = is_textual(content_type, bytes(data))
        text = _decode(bytes(data), content_type) if textual else ""
        # Values captured from this response are masked in it like every other secret.
        if capture is not None:
            secrets = [*secrets, *capture(response.status_code, response.headers, text, truncated)]
        out = {
            **_head(response, content_type, secrets),
            "bodyBytes": len(data),
            "body": mask_secrets(text, secrets),
            "bodyTruncated": truncated,
            "binary": not textual,
            "durationMs": int((time.monotonic() - started) * 1000),
            "redirects": redirects,
        }
        if not textual and options.keep_binary and not truncated and data:
            out["bodyBase64"] = base64.b64encode(bytes(data)).decode()
        return out

    async def _read_stream(
        self,
        chunks: Any,
        head: dict[str, Any],
        secrets: list[str],
        started: float,
        redirects: list[str],
        deadline: _Deadline,
        options: SendOptions,
    ) -> dict[str, Any]:
        """Read an event stream chunk by chunk: report the head, then each event as it completes."""
        if options.on_stream_start is not None:
            options.on_stream_start(head)
        decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        parser = SseParser()
        times: list[int] = []
        text, size, ended = "", 0, "complete"

        def emit(events: list[dict[str, Any]]) -> None:
            for event in events:
                at = int((time.monotonic() - started) * 1000)
                times.append(at)
                if options.on_stream_event is not None:
                    masked = {
                        "event": mask_secrets(event["event"], secrets),
                        "data": mask_secrets(event["data"], secrets),
                    }
                    options.on_stream_event({**event, **masked}, at)

        try:
            while True:
                chunk = await deadline.run(anext(chunks, None))
                if chunk is None:
                    break
                if options.source == "panel":
                    deadline.touch()
                room = max(0, options.max_body_bytes - size)
                piece = decoder.decode(chunk[:room])
                size += min(len(chunk), room)
                text += piece
                emit(parser.push(piece))
                if len(chunk) > room:
                    ended = "limit"
                    break
            if ended == "complete":
                emit(parser.flush())
        except _Cancelled:
            ended = "cancelled"
        except _Expired:
            ended = "timeout"
        return {
            **head,
            "bodyBytes": size,
            "body": mask_secrets(text, secrets),
            "bodyTruncated": ended == "limit",
            "binary": False,
            "durationMs": int((time.monotonic() - started) * 1000),
            "redirects": redirects,
            "stream": {"ended": ended, "times": times},
        }
