"""
Regenerate the `pyharness-composition-reference` skill's `references/packages.md` from the installed entry points.

uv run python scripts/gen_packages.py
"""

from __future__ import annotations

from pyharness_plugin_manager.reference import write_packages

if __name__ == "__main__":
    print(write_packages())
