from __future__ import annotations

import importlib.util
import re
from typing import Any

from pyharness import package_toml

try:
    from langchain.chat_models.base import _BUILTIN_PROVIDERS
except ImportError:  # older langchain without the table
    _BUILTIN_PROVIDERS = {}

_CATALOG = package_toml(__file__)

# ``[PROTOCOLS.<id>]``: title, LangChain type, model options, models listing API.
PROTOCOLS: dict[str, dict[str, Any]] = _CATALOG["PROTOCOLS"]

# Provider types the settings page offers; their integration packages are dependencies of pyxis-harness-llm.
PRESETS: list[str] = _CATALOG["PRESETS"]

# Curated facts per LangChain provider type. Missing types fall back to generic ``api_key`` / ``base_url`` keywords;
# a missing ``models_api`` means no model listing.
CURATED: dict[str, dict[str, Any]] = _CATALOG["CURATED"]


# API version segment at the end of a Gemini base URL.
GEMINI_VERSION = re.compile(r"/v\d+(?:alpha|beta)?\d*$")


def builtin_types() -> dict[str, tuple[str, str]]:
    """LangChain provider → ``(package, class name)``."""
    return {name: (pkg, cls) for name, (pkg, cls, _) in _BUILTIN_PROVIDERS.items()}


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
    """
    Generic ``base_url`` / ``api_key`` → the provider's keyword names; ``None`` values dropped.

    ``openai`` with a custom ``base_url`` defaults to the Chat Completions API (``use_responses_api=False``):
    the common denominator of OpenAI-compatible servers. Set ``use_responses_api`` explicitly to override.

    ``google_genai``: the client appends the API version to ``base_url``; a ``base_url`` that already ends with
    one (``…/v1beta``) is passed without it.
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
    if kind == "google_genai" and isinstance(out.get("base_url"), str):
        out["base_url"] = GEMINI_VERSION.sub("", out["base_url"].rstrip("/"))
    return out
