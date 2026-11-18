"""Release invariants: one version for every distribution, pinned exactly between them; complete metadata."""

from __future__ import annotations

import importlib.util
import tomllib
from pathlib import Path

import pyxis_harness

ROOT = Path(__file__).resolve().parents[1]
PROJECTS = {
    path.parent.name: tomllib.loads(path.read_text())["project"]
    for path in sorted((ROOT / "packages").glob("*/pyproject.toml"))
}
NAMES = {project["name"] for project in PROJECTS.values()}


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


def test_the_entry_distribution_installs_every_bundle():
    entry = PROJECTS["meta"]
    bundles = {project["name"] for directory, project in PROJECTS.items() if directory.startswith("bundle-")}
    assert entry["name"] == "pyxis-harness"
    assert {requirement.split("==")[0] for requirement in entry["dependencies"]} == {"pyxis-harness-core", *bundles}


def test_distributions_carry_their_metadata():
    for directory, project in PROJECTS.items():
        assert project["readme"] == "AGENTS.md" and project["license"] == "MIT", directory
        assert project["authors"] and project["classifiers"] and project["keywords"], directory
        assert {"Homepage", "Repository", "Issues", "Documentation"} <= set(project["urls"]), directory
        hatch = tomllib.loads((ROOT / "packages" / directory / "pyproject.toml").read_text())["tool"]["hatch"]
        assert hatch["build"]["targets"]["sdist"]["force-include"] == {"../../LICENSE": "LICENSE"}, directory


def test_set_version_rewrites_the_version_and_the_pins():
    text = (ROOT / "packages" / "llm" / "pyproject.toml").read_text()
    out = set_version().versioned(text, "0.2.0rc1")
    project = tomllib.loads(out)["project"]
    assert project["version"] == "0.2.0rc1" and "pyxis-harness-core==0.2.0rc1" in project["dependencies"]
    assert [d for d in project["dependencies"] if not d.startswith("pyxis-harness")] == [
        d for d in tomllib.loads(text)["project"]["dependencies"] if not d.startswith("pyxis-harness")
    ]
