"""Release invariants: one version for every distribution, pinned exactly between them; complete metadata."""

from __future__ import annotations

import ast
import importlib.util
import tomllib
from pathlib import Path

import yaml

import pyxis_harness
from pyxis_harness.plugin import PLUGIN_GROUP, load_bundle

ROOT = Path(__file__).resolve().parents[1]
PROJECTS = {
    path.parent.name: tomllib.loads(path.read_text())["project"]
    for path in sorted((ROOT / "packages").glob("*/pyproject.toml"))
}
NAMES = {project["name"] for project in PROJECTS.values()}
HATCH = {
    directory: tomllib.loads((ROOT / "packages" / directory / "pyproject.toml").read_text())["tool"]["hatch"]
    for directory in PROJECTS
}
MODULES = {directory: HATCH[directory]["build"]["targets"]["wheel"].get("packages") or [] for directory in PROJECTS}
PLUGIN_OWNER = {
    plugin: project["name"]
    for project in PROJECTS.values()
    for plugin in project.get("entry-points", {}).get("pyxis_harness.plugins", {})
}
MODULE_OWNER = {module: PROJECTS[directory]["name"] for directory, modules in MODULES.items() for module in modules}
DIRECTORY = {project["name"]: directory for directory, project in PROJECTS.items()}


def declared(directory: str) -> set[str]:
    """Distributions of the workspace that ``directory`` names as dependencies."""
    return {r.split("==")[0].split("[")[0] for r in PROJECTS[directory]["dependencies"]} & NAMES


def installed_with(directory: str) -> set[str]:
    """Distributions of the workspace that installing ``directory`` brings: itself and its dependency closure."""
    seen = {PROJECTS[directory]["name"]}
    queue = [directory]
    while queue:
        for name in declared(queue.pop()) - seen:
            seen.add(name)
            queue.append(DIRECTORY[name])
    return seen


def unguarded_imports(path: Path) -> set[str]:
    """Top-level names of the imports of ``path`` outside ``try`` blocks."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    guarded = {id(node) for block in ast.walk(tree) if isinstance(block, ast.Try) for node in ast.walk(block)}
    names: set[str] = set()
    for node in ast.walk(tree):
        if id(node) in guarded:
            continue
        if isinstance(node, ast.Import):
            names |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.add(node.module.split(".")[0])
    return names


def set_version():
    spec = importlib.util.spec_from_file_location("set_version", ROOT / "scripts" / "set_version.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_every_distribution_shares_the_kernel_version():
    root = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]
    assert {project["version"] for project in PROJECTS.values()} == {root["version"]} == {pyxis_harness.__version__}


def test_distributions_pin_each_other_exactly():
    version = pyxis_harness.__version__
    for directory, project in PROJECTS.items():
        for requirement in project["dependencies"]:
            name = requirement.split("==")[0].split("[")[0]
            if name in NAMES:
                assert requirement == f"{name}=={version}", f"{directory}: {requirement}"


def test_the_entry_distribution_installs_every_plugin_and_mounts_them():
    entry = PROJECTS["meta"]
    others = {project["name"] for directory, project in PROJECTS.items() if directory != "meta"}
    assert entry["name"] == "pyxis-harness"
    assert {requirement.split("==")[0] for requirement in entry["dependencies"]} == others
    assert entry["entry-points"]["pyxis_harness.bundles"] == {"base": "pyxis_harness_bundle_base:BUNDLE"}
    # Every plugin of the workspace is mounted by the base bundle.
    plugins = {name for project in PROJECTS.values() for name in project.get("entry-points", {}).get(PLUGIN_GROUP, {})}
    mounted = {op.name for op in load_bundle("base").ops}
    assert plugins - mounted == {"pyxis-harness-checkpoint-postgres"}  # the alternative to checkpoint-sqlite


def test_distributions_carry_their_metadata():
    for directory, project in PROJECTS.items():
        assert project["readme"] == "AGENTS.md" and project["license"] == "MIT", directory
        assert project["authors"] and project["classifiers"] and project["keywords"], directory
        assert {"Homepage", "Repository", "Issues", "Documentation"} <= set(project["urls"]), directory
        assert HATCH[directory]["build"]["targets"]["sdist"]["force-include"] == {"../../LICENSE": "LICENSE"}, directory


def test_set_version_rewrites_the_version_and_the_pins():
    text = (ROOT / "packages" / "llm" / "pyproject.toml").read_text()
    out = set_version().versioned(text, "0.2.0rc1")
    project = tomllib.loads(out)["project"]
    assert project["version"] == "0.2.0rc1" and "pyxis-harness-core==0.2.0rc1" in project["dependencies"]
    assert [d for d in project["dependencies"] if not d.startswith("pyxis-harness")] == [
        d for d in tomllib.loads(text)["project"]["dependencies"] if not d.startswith("pyxis-harness")
    ]


def test_a_bundle_installs_every_plugin_it_names():
    for directory in PROJECTS:
        for bundle in (ROOT / "packages" / directory).glob("*/bundle.yaml"):
            named = [op["name"] for op in yaml.safe_load(bundle.read_text()).get("patch") or [] if "name" in op]
            missing = sorted({PLUGIN_OWNER[name] for name in named} - installed_with(directory))
            assert not missing, f"{directory}: bundle.yaml names plugins of {missing}, which it does not depend on"


def test_a_distribution_declares_the_distributions_it_imports():
    for directory, modules in MODULES.items():
        imported: set[str] = set()
        for module in modules:
            for path in (ROOT / "packages" / directory / module).rglob("*.py"):
                imported |= unguarded_imports(path)
        needed = {MODULE_OWNER[name] for name in imported if name in MODULE_OWNER} - {PROJECTS[directory]["name"]}
        assert needed <= declared(directory), f"{directory}: imports {sorted(needed - declared(directory))} undeclared"


def test_the_entry_distribution_installs_every_distribution():
    assert installed_with("meta") == NAMES
