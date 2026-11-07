"""``web`` bundle: the ``web_search`` and ``web_fetch`` tools (``pyharness-web-tools``).

Optional: on by default, switched off on the Plugins page.
"""

from __future__ import annotations

from pathlib import Path

BUNDLE = Path(__file__).with_name("bundle.yaml")

__all__ = ["BUNDLE"]
