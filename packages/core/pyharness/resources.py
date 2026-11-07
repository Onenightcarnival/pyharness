"""Data files shipped inside a package: TOML tables next to a module.

| function                       | file            | use                                              |
|--------------------------------|-----------------|--------------------------------------------------|
| ``package_toml(file, name)``   | ``config.toml`` | data tables: endpoints, catalogs, type maps      |
| ``package_prompts(file, name)``| ``prompts.toml``| model-visible text; string leaves are stripped   |

Placeholders in prompt text use :class:`string.Template` syntax (``${name}``); a literal ``$`` is ``$$``.
"""

from __future__ import annotations

import tomllib
from functools import cache
from pathlib import Path
from typing import Any


@cache
def package_toml(module_file: str, name: str = "config.toml") -> dict[str, Any]:
    """The parsed TOML file ``name`` next to ``module_file`` (a module's ``__file__``); parsed once per path."""
    return tomllib.loads(Path(module_file).with_name(name).read_text(encoding="utf-8"))


def _strip_leaves(value: Any) -> Any:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        return {k: _strip_leaves(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_strip_leaves(v) for v in value]
    return value


@cache
def package_prompts(module_file: str, name: str = "prompts.toml") -> dict[str, Any]:
    """The parsed ``name`` next to ``module_file`` with every string value stripped of surrounding whitespace."""
    return _strip_leaves(package_toml(module_file, name))
