"""``references/packages.md`` of the ``pyharness-composition-reference`` skill, rendered from the installed entry points.

``python scripts/gen_packages.py`` writes it; ``tests/test_creator.py`` fails when the file is stale.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pyharness.plugin import bundle_entry_points, load_bundle, load_plugin, plugin_entry_points

PACKAGES_MD = Path(__file__).with_name("skills") / "pyharness-composition-reference" / "references" / "packages.md"

HEADER = """\
# Installed plugin packages and bundles

Generated from the `pyharness.plugins` and `pyharness.bundles` entry points of the environment: `python scripts/gen_packages.py`.
Plugins installed into a profile after generation: `plugin_manager action=list`.

Columns: `kind` is `service` (provides the service under `provides`) or `function` (`apply(ctx, config)`); `inject` lists the
services the entry waits for; `config` says whether the entry accepts `config`.
"""


def _first_line(text: str | None) -> str:
    for line in (text or "").splitlines():
        line = line.strip()
        if line:
            return line.replace("|", "\\|")
    return ""


def plugin_rows() -> list[dict[str, Any]]:
    rows = []
    for name in sorted(plugin_entry_points()):
        try:
            spec = load_plugin(name)
        except Exception as exc:  # noqa: BLE001 - a broken package is listed with its error
            rows.append({"name": name, "kind": "error", "provides": "", "inject": "", "config": "", "doc": f"{type(exc).__name__}: {exc}"})
            continue
        rows.append(
            {
                "name": name,
                "kind": spec.kind,
                "provides": spec.service_cls.key if spec.service_cls is not None else "",
                "inject": ", ".join(spec.inject),
                "config": "yes" if spec.config_model is not None else "no",
                "doc": _first_line(spec.doc),
            }
        )
    return rows


def bundle_rows() -> list[dict[str, Any]]:
    rows = []
    for name in sorted(bundle_entry_points()):
        try:
            info = load_bundle(name)
        except Exception as exc:  # noqa: BLE001
            rows.append({"name": name, "title": "", "description": f"{type(exc).__name__}: {exc}", "entries": ""})
            continue
        entries = ", ".join(f"`{op.id}`" for op in info.ops)
        rows.append({"name": name, "title": info.title, "description": _first_line(info.description), "entries": entries})
    return rows


def render_packages() -> str:
    out = [HEADER, "## Plugins", "", "| entry point | kind | provides | inject | config | contract |", "|---|---|---|---|---|---|"]
    for r in plugin_rows():
        out.append(f"| `{r['name']}` | {r['kind']} | {r['provides']} | {r['inject']} | {r['config']} | {r['doc']} |")
    out += ["", "## Bundles", "", "| bundle | title | description | entries (patch op ids) |", "|---|---|---|---|"]
    for r in bundle_rows():
        out.append(f"| `{r['name']}` | {r['title']} | {r['description']} | {r['entries']} |")
    return "\n".join(out) + "\n"


def write_packages(path: Path = PACKAGES_MD) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_packages(), encoding="utf-8")
    return path


__all__ = ["PACKAGES_MD", "bundle_rows", "plugin_rows", "render_packages", "write_packages"]
