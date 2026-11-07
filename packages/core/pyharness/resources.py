"""Data files shipped inside a package: TOML tables next to a module."""

from __future__ import annotations

import tomllib
from functools import cache
from pathlib import Path
from typing import Any


@cache
def package_toml(module_file: str, name: str = "config.toml") -> dict[str, Any]:
    """The parsed TOML file ``name`` next to ``module_file`` (a module's ``__file__``); parsed once per path."""
    return tomllib.loads(Path(module_file).with_name(name).read_text(encoding="utf-8"))
