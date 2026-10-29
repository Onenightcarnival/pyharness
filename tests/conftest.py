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
    monkeypatch.setenv("PYTHONPATH", os.pathsep.join([str(TESTS), os.environ.get("PYTHONPATH", "")]))
    monkeypatch.delenv("PYH_MODEL", raising=False)
    (tmp_path / "workspace").mkdir()
    return home


@pytest.fixture
def example_bundle() -> Path:
    return ROOT / "examples" / "pyharness-audit"
