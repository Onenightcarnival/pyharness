"""Package documentation: one ``AGENTS.md`` per package; the sources carry no file-header documentation."""

from __future__ import annotations

import ast
import tomllib
from pathlib import Path

from pyxis_harness.plugin import load_plugin, plugin_entry_points

ROOT = Path(__file__).resolve().parents[1]
PACKAGES = sorted(p for p in (ROOT / "packages").iterdir() if (p / "pyproject.toml").is_file())
CONTENT_DIRS = {"__pycache__", "skills", "vendor"}  # shipped content, not sources of the package
COMMENT = {".toml": "#", ".js": "//"}


def sources(package: Path) -> list[Path]:
    out = []
    for module in sorted(d for d in package.iterdir() if (d / "__init__.py").is_file()):
        out.extend(
            path
            for path in sorted(module.rglob("*"))
            if path.suffix in (".py", *COMMENT) and not CONTENT_DIRS & set(path.relative_to(module).parts)
        )
    return out


def leading_comment_is_header(text: str, prefix: str) -> bool:
    """A comment block at the top that a blank line or the end of the file follows; one attached to an item is not."""
    lines = text.split("\n")
    count = next((i for i, line in enumerate(lines) if not line.startswith(prefix)), len(lines))
    return count > 0 and (count == len(lines) or not lines[count].strip())


def test_every_package_has_an_agents_md_and_ships_it():
    assert len(PACKAGES) >= 30
    for package in PACKAGES:
        docs = package / "AGENTS.md"
        assert docs.is_file() and docs.read_text().startswith("# "), f"{package.name}: AGENTS.md with a title"
        wheel = tomllib.loads((package / "pyproject.toml").read_text())["tool"]["hatch"]["build"]["targets"]["wheel"]
        (module,) = wheel["packages"]
        assert wheel["force-include"] == {"AGENTS.md": f"{module}/AGENTS.md"}, package.name


def test_sources_have_no_file_header():
    headed = []
    for package in PACKAGES:
        for path in sources(package):
            text = path.read_text()
            if path.suffix == ".py":
                if ast.get_docstring(ast.parse(text)) is not None:
                    headed.append(path)
            elif leading_comment_is_header(text, COMMENT[path.suffix]):
                headed.append(path)
    assert not headed, "file-header documentation belongs in the package's AGENTS.md: " + ", ".join(
        str(p.relative_to(ROOT)) for p in headed
    )


def test_plugin_specs_report_their_docs():
    assert load_plugin("pyxis-harness-llm").docs == str(ROOT / "packages" / "llm" / "AGENTS.md")
    for name in plugin_entry_points():
        spec = load_plugin(name)
        assert spec.docs and Path(spec.docs).is_file(), name
        assert spec.doc, f"{name}: one-line description"
