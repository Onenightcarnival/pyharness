"""
``ctx.httpClient``: HTTP API request tool (aligned with dsh-http): API targets with injected auth, saved
requests, a request history shared by the page and the agent, and event streams read as they arrive.

| member       | contract                                                                              |
|--------------|---------------------------------------------------------------------------------------|
| ``store``    | :class:`TargetStore`: targets (secrets included) and the switches ``agentTools``, ``historyLimit`` |
| ``requests`` | :class:`RequestStore`: saved requests per target and for the ``direct`` scope          |
| ``history``  | :class:`HistoryStore`: recorded exchanges, newest first                               |
| ``engine``   | :class:`HttpEngine`: ``send(ref, request, options)``, ``test(ref)``                    |
| ``sync()``   | register the ``http_*`` tools and the prompt section while ``agentTools`` is on        |

| target field       | meaning                                                                         |
|--------------------|---------------------------------------------------------------------------------|
| ``baseUrl``        | http(s) scheme, host and optional path prefix; request paths join below it      |
| ``name``           | defaults to the host; the agent refers to the target by it                      |
| ``auth``           | ``none``, ``bearer``, ``basic``, ``header``, ``query``; the secret stays in the store |
| ``headers``        | sent on every request; a request header of the same name overrides              |
| ``variables``      | ``{{name}}`` substituted in path, query, headers and body; not secret           |
| ``allowedHosts``   | hosts besides the base host an absolute URL or a redirect may reach; ``*.example.com`` |
| ``allowMutations`` | the agent may use POST / PUT / PATCH / DELETE, each call with ``confirm=true``  |
| ``allowPrivate``   | requests may reach loopback, link-local and private addresses                   |
| ``timeoutMs``      | 1 000–120 000, covering redirects and the body; default 30 000                  |

A request without a target (the ``direct`` scope) carries a full URL, reaches any host, gets no injected auth, and
belongs to the page only: the agent can neither send nor list it.

Tools (shapes as dsh-http), registered while ``agentTools`` is on: ``http_targets``, ``http_request``,
``http_history``.

| config       | meaning                                                                               |
|--------------|---------------------------------------------------------------------------------------|
| ``data_dir`` | directory of the three files below (default ``<profile data>/toolkit/http-client``)   |

| file              | content                                                                        |
|-------------------|--------------------------------------------------------------------------------|
| ``targets.json``  | targets and switches, mode 0600; auth secrets in plain text                    |
| ``requests.json`` | saved requests, at most 500 per target; a request's own auth in plain text     |
| ``history.jsonl`` | exchanges, 200 kept by default (``historyLimit`` 10–1 000), bodies capped at 32 KiB |

Routes under ``/api/http-client`` serve the HTTP page: ``targets``, ``requests``, ``settings``, ``send``,
``history``, ``test``.

| module       | content                                                                              |
|--------------|--------------------------------------------------------------------------------------|
| ``config``   | ``Config``                                                                           |
| ``protocol`` | wire constants, ``join_url``, ``substitute``, ``SseParser``                           |
| ``store``    | the three stores and the validation of their records                                 |
| ``engine``   | ``HttpEngine``: host policy, auth, redirects, body caps, event streams, masking       |
| ``tools``    | the ``http_*`` tools                                                                  |
| ``routes``   | management routes                                                                    |
| ``service``  | ``HttpClientService``                                                                |
"""

from __future__ import annotations

from .config import Config
from .engine import HttpEngine, PolicyError, SendOptions
from .service import GUIDANCE, HttpClientService
from .store import HistoryStore, RequestStore, StoreError, TargetStore

__all__ = [
    "GUIDANCE",
    "Config",
    "HistoryStore",
    "HttpClientService",
    "HttpEngine",
    "PolicyError",
    "RequestStore",
    "SendOptions",
    "StoreError",
    "TargetStore",
]
