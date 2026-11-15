"""
``ctx.gateway``: local LLM API gateway. The model routes of ``ctx.llm`` are served over the OpenAI Chat
Completions, OpenAI Responses and Anthropic Messages protocols on a listener of its own, with API keys and
per-request usage accounting (aligned with dsh-gateway).

| member              | contract                                                                     |
|---------------------|------------------------------------------------------------------------------|
| ``status()``        | settings, listener state (``listening``, ``listenError``), models, keys      |
| ``save_settings()`` | persist the complete settings object and restart the listener                |
| ``settings``        | :class:`SettingsStore`: ``enabled``, ``host``, ``port``, ``aliases``, ``pricing`` |
| ``keys``            | :class:`KeyStore`: create, update, remove, reveal, verify                    |
| ``usage``           | :class:`UsageStore`: the request ledger and its range summaries              |
| ``app``             | the gateway ASGI application                                                 |

| endpoint                      | protocol                                                           |
|-------------------------------|--------------------------------------------------------------------|
| ``GET /v1/models``            | OpenAI list; Anthropic shape for ``anthropic-version`` or ``x-api-key`` requests |
| ``POST /v1/chat/completions`` | OpenAI Chat Completions; ``stream``, ``stream_options.include_usage`` |
| ``POST /v1/responses``        | OpenAI Responses; ``stream`` with ``sequence_number`` events       |
| ``POST /v1/messages``         | Anthropic Messages; ``stream``                                     |

Every request carries a key in ``Authorization: Bearer <key>`` or ``x-api-key: <key>``. A model id is
``route:model`` of ``ctx.llm``; a request name resolves through ``aliases`` first and has no default. Image inputs
(``data:`` URLs, ``http(s)`` URLs; PNG, JPEG, WebP, GIF) reach the model as ``data:`` URLs.

| config            | meaning                                                                        |
|-------------------|--------------------------------------------------------------------------------|
| ``listen``        | initial listener state before the settings file exists (default on)           |
| ``host``, ``port``| initial listener address (default ``127.0.0.1:8766``)                          |
| ``data_dir``      | directory of the three files below (default ``<profile data>/toolkit/gateway``) |
| ``max_body_bytes``| request body limit (default 32 MiB)                                            |

| file              | content                                                                        |
|-------------------|--------------------------------------------------------------------------------|
| ``settings.json`` | listener fields edited on the page; ``aliases`` and ``pricing`` edited in the file |
| ``keys.json``     | every key in full, mode 0600; a key named ``default`` is generated on the first start |
| ``usage.sqlite``  | one row per authenticated protocol request; rows older than 400 days are deleted |

The listener binds on ``app/serve``; a bind failure is reported in ``status()`` and does not fail the boot.
Routes under ``/api/gateway`` serve the API gateway page: ``status``, ``settings``, ``keys``, ``usage``.

| module                 | content                                                                   |
|------------------------|---------------------------------------------------------------------------|
| ``config``             | ``Config``                                                                |
| ``settings``, ``keys``, ``usage`` | the three stores                                               |
| ``models``             | ``ModelCatalog``: model ids and alias resolution                          |
| ``images``             | ``ImageResolver``                                                         |
| ``drafts``             | ``ParsedRequest``, ``Generation``, ``GatewayError``, field readers        |
| ``chunks``             | the stream vocabulary, ``normalize()``, ``BlockAssembler``                |
| ``openai_chat``, ``openai_responses``, ``anthropic_messages`` | parsing and encoding of one protocol each |
| ``backend``            | ``LangChainBackend``: one request → one ``astream`` on a route            |
| ``server``             | the gateway application                                                   |
| ``listener``           | ``Listener``: the uvicorn server of the application                       |
| ``routes``             | management routes                                                         |
| ``service``            | ``GatewayService``                                                        |
"""

from __future__ import annotations

from .config import Config
from .drafts import GatewayError
from .keys import KeyStore, KeyStoreError
from .models import ModelCatalog, ModelResolutionError
from .service import GatewayService
from .settings import SettingsError, SettingsStore
from .usage import UsageStore

__all__ = [
    "Config",
    "GatewayError",
    "GatewayService",
    "KeyStore",
    "KeyStoreError",
    "ModelCatalog",
    "ModelResolutionError",
    "SettingsError",
    "SettingsStore",
    "UsageStore",
]
