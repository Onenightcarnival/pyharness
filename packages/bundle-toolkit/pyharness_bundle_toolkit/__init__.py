"""``toolkit`` bundle: the built-in toolkit modules (memory, relational databases, S3, skills, MCP page, subscriptions,
OpenTelemetry export). ``builtin: true``: part of every profile, never switched off; the Web UI hides sidebar
entries instead.
"""

from pathlib import Path

BUNDLE = Path(__file__).with_name("bundle.yaml")

__all__ = ["BUNDLE"]
