"""
Regenerate the `pyxis-harness-composition-reference` skill's `references/packages.md` from the installed entry points.

uv run python scripts/gen_packages.py
"""

from __future__ import annotations

from pyxis_harness_plugin_manager.reference import write_packages

if __name__ == "__main__":
    print(write_packages())
