"""``ctx.llm``: chat-model routes over LangChain provider integrations.

A **route** is a configured provider under ``config.providers[route]``: its ``type`` names a LangChain provider
(``init_chat_model`` ``model_provider``, or a factory registered with :meth:`LLMService.register`), its connection
facts (``base_url``, ``api_key_env``), and its model catalog. A model spec is ``"route:model"``.

| method                | purpose                                                                 |
|-----------------------|-------------------------------------------------------------------------|
| ``resolve(spec)``     | chat model for ``route:model``; instances cached until ``update``       |
| ``build(spec, ...)``  | a new chat model with per-request overrides; not cached                 |
| ``update(...)``       | replace the live configuration; the next request uses it               |
| ``describe()``        | routes with credential state (never the value) and the provider catalog |
| ``directory()``       | model choices for selectors, grouped by route                           |
| ``probe(...)``        | one short completion                                                    |
| ``list_models(...)``  | model ids served by an endpoint (OpenAI, Anthropic, Gemini, Ollama listings) |
| ``retry_policy(spec)`` | the :class:`RetryPolicy` of the spec's route, else the global one, else ``None`` |

Credentials: ``api_key_env`` is a reference resolved through the environment, then the profile credential store;
``api_key`` in the configuration is accepted and discouraged.

| ``type``                | source                                                                    |
|-------------------------|---------------------------------------------------------------------------|
| presets (:data:`PRESETS`) | offered by the settings page; their packages are dependencies of this plugin |
| other LangChain built-ins | accepted in configuration (``langchain.chat_models.base._BUILTIN_PROVIDERS``) |
| registered              | :meth:`LLMService.register` (``echo`` built in)                           |

A failed model call has one failure code (:mod:`.failures`); a retry policy retries the codes it lists, with
backoff, on top of the provider client's own retries. A route without a policy inherits ``config.retry``.

Each model entry carries its input modalities (``input``: ``text``, ``image``); selectors and attachment handling
read them.
"""

from __future__ import annotations

from .catalog import CURATED, PRESETS, PROTOCOLS, translate_options, type_info
from .config import LLMConfig, LLMConfigError, ModelEntry, ProviderConfig, RetryPolicy, mask_secret, split_spec
from .failures import CONTINUABLE_CODES, RETRY_CHOICES, TRANSIENT_CODES, failure_code, retry_after_ms
from .service import EchoChatModel, LLMService

__all__ = [
    "CONTINUABLE_CODES",
    "CURATED",
    "PRESETS",
    "PROTOCOLS",
    "RETRY_CHOICES",
    "TRANSIENT_CODES",
    "EchoChatModel",
    "LLMConfig",
    "LLMConfigError",
    "LLMService",
    "ModelEntry",
    "ProviderConfig",
    "RetryPolicy",
    "failure_code",
    "mask_secret",
    "retry_after_ms",
    "split_spec",
    "translate_options",
    "type_info",
]
