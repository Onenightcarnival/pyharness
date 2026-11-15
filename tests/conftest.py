from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

TESTS = Path(__file__).parent
ROOT = TESTS.parent
sys.path.insert(0, str(TESTS))


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "home"
    monkeypatch.setenv("PYH_HOME", str(home))
    monkeypatch.setenv("PYH_CWD", str(tmp_path / "workspace"))
    monkeypatch.setenv("PYH_WORKSPACE", str(tmp_path / "workspace"))
    monkeypatch.setenv("PYTHONPATH", os.pathsep.join([str(TESTS), os.environ.get("PYTHONPATH", "")]))
    monkeypatch.delenv("PYH_MODEL", raising=False)
    (tmp_path / "workspace").mkdir()
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
def example_bundle() -> Path:
    return ROOT / "examples" / "pyharness-audit"
