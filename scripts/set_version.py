"""
Set the one version every distribution shares: `version`, the `==` pins between the distributions, the kernel's
`__version__`, then the lock file.

uv run python scripts/set_version.py 0.1.0rc1
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

from packaging.version import Version

ROOT = Path(__file__).resolve().parents[1]
PREFIX = "pyxis-harness"
VERSION = re.compile(r'^version = "[^"]+"$', re.MULTILINE)
PIN = re.compile(rf'("{PREFIX}(?:-[a-z0-9-]+)?==)[^"]+(")')
DUNDER = re.compile(r'^__version__ = "[^"]+"$', re.MULTILINE)


def pyprojects() -> list[Path]:
    return [ROOT / "pyproject.toml", *sorted((ROOT / "packages").glob("*/pyproject.toml"))]


def versioned(text: str, version: str) -> str:
    """``text`` of a pyproject with the project version and the pins on the distributions set to ``version``."""
    text, count = VERSION.subn(f'version = "{version}"', text, count=1)
    if count != 1:
        raise SystemExit("a pyproject.toml without a `version = ...` line")
    return PIN.sub(rf"\g<1>{version}\g<2>", text)


def main(argv: list[str]) -> None:
    if len(argv) != 1:
        raise SystemExit(__doc__)
    version = str(Version(argv[0]))  # normalized; an invalid version raises
    for path in pyprojects():
        path.write_text(versioned(path.read_text(encoding="utf-8"), version), encoding="utf-8")
    kernel = ROOT / "packages" / "core" / "pyxis_harness" / "__init__.py"
    kernel.write_text(DUNDER.sub(f'__version__ = "{version}"', kernel.read_text(encoding="utf-8")), encoding="utf-8")
    subprocess.run(["uv", "lock"], cwd=ROOT, check=True)
    print(f"{len(pyprojects())} pyproject.toml files at {version}")


if __name__ == "__main__":
    main(sys.argv[1:])
