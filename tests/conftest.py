from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

try:
    from pip._internal.locations import USER_CACHE_DIR as PIP_CACHE
except ImportError:  # the uv fallback installs bundles
    PIP_CACHE = None

TESTS = Path(__file__).parent
ROOT = TESTS.parent
UV_CACHE = os.environ.get("UV_CACHE_DIR") or str(Path.home() / ".cache" / "uv")
sys.path.insert(0, str(TESTS))


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "home"
    monkeypatch.setenv("PYH_HOME", str(home))
    monkeypatch.setenv("PYH_CWD", str(tmp_path / "cwd"))
    monkeypatch.setenv("HOME", str(tmp_path / "user"))  # the default workspace lies under the user's Documents
    for variable, cache in (("PIP_CACHE_DIR", PIP_CACHE), ("UV_CACHE_DIR", UV_CACHE)):  # installers keep their caches
        if cache:
            monkeypatch.setenv(variable, cache)
    monkeypatch.setenv("PYTHONPATH", os.pathsep.join([str(TESTS), os.environ.get("PYTHONPATH", "")]))
    monkeypatch.delenv("PYH_MODEL", raising=False)
    (tmp_path / "cwd").mkdir()
    (tmp_path / "user").mkdir()
    path_before = list(sys.path)
    yield home
    # Profile sites activated by this test leave sys.path and the module cache, so a later test's bundle of the
    # same name resolves to its own site rather than to this test's (possibly removed) files.
    sys.path[:] = path_before
    prefix = str(tmp_path)
    for name, module in list(sys.modules.items()):
        file = getattr(module, "__file__", None)
        if file and file.startswith(prefix):
            del sys.modules[name]


@pytest.fixture
def workspace(home: Path) -> Path:
    """Default workspace of the ``web`` profile."""
    root = Path.home() / "Documents" / "pyharness" / "web" / "default-workspace"
    root.mkdir(parents=True)
    return root


@pytest.fixture
def example_bundle() -> Path:
    return ROOT / "examples" / "pyharness-audit"
