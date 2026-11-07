"""Provider catalog: wire protocols, the settings-page presets, curated facts per LangChain provider type."""

from __future__ import annotations

import importlib.util
from typing import Any

PROTOCOLS: dict[str, dict[str, Any]] = {
    "openai-chat": {
        "title": "OpenAI Chat Completions",
        "type": "openai",
        "options": {"use_responses_api": False},
        "models_api": "openai",
    },
    "openai-responses": {
        "title": "OpenAI Responses",
        "type": "openai",
        "options": {"use_responses_api": True},
        "models_api": "openai",
    },
    "anthropic-messages": {
        "title": "Anthropic Messages",
        "type": "anthropic",
        "options": {},
        "models_api": "anthropic",
    },
}

# Provider types the settings page offers; their integration packages are dependencies of pyharness-llm.
PRESETS = ["openai", "anthropic", "deepseek", "google_genai", "openrouter"]

# Curated facts per LangChain provider type. Missing types fall back to generic ``api_key`` / ``base_url`` keywords.
CURATED: dict[str, dict[str, Any]] = {
    "openai": {
        "title": "OpenAI",
        "env": "OPENAI_API_KEY",
        "base_url": "https://api.openai.com/v1",
        "models_api": "openai",
    },
    "openrouter": {
        "title": "OpenRouter",
        "env": "OPENROUTER_API_KEY",
        "base_url": "https://openrouter.ai/api/v1",
        "models_api": "openai",
    },
    "azure_openai": {
        "title": "Azure OpenAI",
        "env": "AZURE_OPENAI_API_KEY",
        "keys": {"base_url": "azure_endpoint"},
        "models_api": None,
    },
    "anthropic": {
        "title": "Anthropic",
        "env": "ANTHROPIC_API_KEY",
        "base_url": "https://api.anthropic.com",
        "models_api": "anthropic",
    },
    "deepseek": {
        "title": "DeepSeek",
        "env": "DEEPSEEK_API_KEY",
        "base_url": "https://api.deepseek.com",
        "models_api": "openai",
        "models": [
            {"id": "deepseek-chat", "name": "DeepSeek Chat"},
            {"id": "deepseek-reasoner", "name": "DeepSeek Reasoner"},
        ],
    },
    "google_genai": {
        "title": "Google Gemini",
        "env": "GOOGLE_API_KEY",
        "keys": {"api_key": "google_api_key"},
        "models_api": None,
    },
    "google_vertexai": {"title": "Google Vertex AI", "credentials": False, "models_api": None},
    "google_anthropic_vertex": {"title": "Anthropic on Vertex AI", "credentials": False, "models_api": None},
    "bedrock": {"title": "Amazon Bedrock", "credentials": False, "models_api": None},
    "bedrock_converse": {"title": "Amazon Bedrock Converse", "credentials": False, "models_api": None},
    "anthropic_bedrock": {"title": "Anthropic on Bedrock", "credentials": False, "models_api": None},
    "groq": {
        "title": "Groq",
        "env": "GROQ_API_KEY",
        "base_url": "https://api.groq.com/openai/v1",
        "models_api": "openai",
    },
    "mistralai": {
        "title": "Mistral AI",
        "env": "MISTRAL_API_KEY",
        "base_url": "https://api.mistral.ai/v1",
        "keys": {"base_url": "endpoint"},
        "models_api": "openai",
    },
    "fireworks": {
        "title": "Fireworks AI",
        "env": "FIREWORKS_API_KEY",
        "base_url": "https://api.fireworks.ai/inference/v1",
        "models_api": "openai",
    },
    "together": {
        "title": "Together AI",
        "env": "TOGETHER_API_KEY",
        "base_url": "https://api.together.xyz/v1",
        "models_api": "openai",
    },
    "xai": {"title": "xAI", "env": "XAI_API_KEY", "base_url": "https://api.x.ai/v1", "models_api": "openai"},
    "perplexity": {
        "title": "Perplexity",
        "env": "PPLX_API_KEY",
        "base_url": "https://api.perplexity.ai",
        "models_api": "openai",
    },
    "ollama": {"title": "Ollama", "credentials": False, "base_url": "http://localhost:11434", "models_api": "ollama"},
    "cohere": {"title": "Cohere", "env": "COHERE_API_KEY", "keys": {"api_key": "cohere_api_key"}, "models_api": None},
    "huggingface": {"title": "Hugging Face", "env": "HUGGINGFACEHUB_API_TOKEN", "models_api": None},
    "nvidia": {"title": "NVIDIA", "env": "NVIDIA_API_KEY", "models_api": None},
    "ibm": {"title": "IBM watsonx", "env": "WATSONX_APIKEY", "models_api": None},
    "litellm": {"title": "LiteLLM", "credentials": False, "models_api": None},
    "upstage": {"title": "Upstage", "env": "UPSTAGE_API_KEY", "models_api": None},
    "baseten": {"title": "Baseten", "env": "BASETEN_API_KEY", "models_api": None},
    "meta": {"title": "Meta Llama API", "env": "LLAMA_API_KEY", "models_api": None},
    "azure_ai": {
        "title": "Azure AI",
        "env": "AZURE_AI_CREDENTIAL",
        "keys": {"base_url": "endpoint", "api_key": "credential"},
        "models_api": None,
    },
    "langsmith": {"title": "LangSmith", "env": "LANGSMITH_API_KEY", "models_api": None},
    "bedrock_mantle_anthropic": {"title": "Bedrock Mantle (Anthropic)", "credentials": False, "models_api": None},
    "bedrock_mantle_openai": {"title": "Bedrock Mantle (OpenAI)", "credentials": False, "models_api": None},
    "echo": {
        "title": "Echo (placeholder, no credentials)",
        "credentials": False,
        "models_api": None,
        "models": [{"id": "echo", "name": "Echo"}],
    },
}


def builtin_types() -> dict[str, tuple[str, str]]:
    """LangChain provider → ``(package, class name)``."""
    try:
        from langchain.chat_models.base import _BUILTIN_PROVIDERS

        return {name: (pkg, cls) for name, (pkg, cls, _) in _BUILTIN_PROVIDERS.items()}
    except Exception:  # pragma: no cover - older langchain
        return {}


def type_info(kind: str) -> dict[str, Any]:
    """Catalog facts for a provider type: title, package, installed, env, base_url, keys, credentials, models_api."""
    builtin = builtin_types().get(kind)
    curated = CURATED.get(kind, {})
    package = builtin[0].split(".")[0] if builtin else None
    installed = importlib.util.find_spec(package) is not None if package else kind == "echo"
    return {
        "id": kind,
        "title": curated.get("title", kind.replace("_", " ").title()),
        "package": package,
        "preset": kind in PRESETS,
        "installed": installed,
        "env": curated.get(
            "env", f"{kind.upper()}_API_KEY" if curated.get("credentials", True) and kind != "echo" else None
        ),
        "base_url": curated.get("base_url"),
        "keys": {"api_key": "api_key", "base_url": "base_url", **curated.get("keys", {})},
        "credentials": curated.get("credentials", True),
        "models_api": curated.get("models_api"),
        "models": list(curated.get("models", [])),
        "curated": kind in CURATED,
    }


def translate_options(kind: str, options: dict[str, Any]) -> dict[str, Any]:
    """Generic ``base_url`` / ``api_key`` → the provider's keyword names; ``None`` values dropped.

    ``openai`` with a custom ``base_url`` defaults to the Chat Completions API (``use_responses_api=False``):
    the common denominator of OpenAI-compatible servers. Set ``use_responses_api`` explicitly to override.
    """
    keys = type_info(kind)["keys"] if kind else {}
    out: dict[str, Any] = {}
    for key, value in options.items():
        if value is None:
            continue
        out[keys.get(key, key)] = value
    base_url = options.get("base_url")
    if kind == "openai" and isinstance(base_url, str) and "api.openai.com" not in base_url:
        out.setdefault("use_responses_api", False)
    return out
