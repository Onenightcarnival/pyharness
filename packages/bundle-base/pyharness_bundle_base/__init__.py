"""``base`` bundle: the plugin set of the ``web`` profile template."""

from __future__ import annotations

from pathlib import Path

BUNDLE = Path(__file__).with_name("bundle.yaml")

__all__ = ["BUNDLE"]
