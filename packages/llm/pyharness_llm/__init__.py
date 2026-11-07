"""``ctx.llm``: chat-model routes over LangChain provider integrations.

A **route** is a configured provider under ``config.providers[route]``: its ``type`` names a LangChain provider
(``init_chat_model`` ``model_provider``, or a factory registered with :meth:`LLMService.register`), its connection
facts (``base_url``, ``api_key_env``), and its model catalog. A model spec is ``"route:model"``.

| method                | purpose                                                                 |
|-----------------------|-------------------------------------------------------------------------|
| ``resolve(spec)``     | chat model for ``route:model``; instances cached until ``update``       |
| ``update(...)``       | replace the live configuration; the next request uses it               |
| ``describe()``        | routes with credential state (never the value) and the provider catalog |
| ``directory()``       | model choices for selectors, grouped by route                           |
| ``probe(...)``        | one short completion                                                    |
| ``list_models(...)``  | model ids served by an endpoint (OpenAI, Anthropic, Ollama listings)    |

Credentials: ``api_key_env`` is a reference resolved through the environment, then the profile credential store;
``api_key`` in the configuration is accepted and discouraged.

| ``type``                | source                                                                    |
|-------------------------|---------------------------------------------------------------------------|
| presets (:data:`PRESETS`) | offered by the settings page; their packages are dependencies of this plugin |
| other LangChain built-ins | accepted in configuration (``langchain.chat_models.base._BUILTIN_PROVIDERS``) |
| registered              | :meth:`LLMService.register` (``echo`` built in)                           |

Each model entry carries its input modalities (``input``: ``text``, ``image``); selectors and attachment handling
read them.
"""

from .catalog import CURATED, PRESETS, PROTOCOLS, translate_options, type_info
from .config import LLMConfig, LLMConfigError, ModelEntry, ProviderConfig, mask_secret, split_spec
from .service import EchoChatModel, LLMService

__all__ = [
    "CURATED",
    "PRESETS",
    "PROTOCOLS",
    "EchoChatModel",
    "LLMConfig",
    "LLMConfigError",
    "LLMService",
    "ModelEntry",
    "ProviderConfig",
    "mask_secret",
    "split_spec",
    "translate_options",
    "type_info",
]
