"""Process model, real processes: exit 75 → restart; boot failure → rollback to last-known-good."""

from __future__ import annotations

import json
import os
import subprocess
import sys

from pyharness import Profile


def test_restart_into_broken_config_rolls_back(home, tmp_path):
    profile = Profile.init("sup", template="empty", home=str(home))
    markers = tmp_path / "markers"
    profile.save_patch([{"id": "flow", "name": "testkit.lifecycle_flow", "config": {"marker_dir": str(markers)}}])

    env = dict(os.environ)
    proc = subprocess.run(
        [sys.executable, "-m", "pyharness.cli", "--home", str(home), "run", "-p", "sup", "--boot-timeout", "60"],
        env=env,
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert proc.returncode == 0, proc.stderr[-3000:]

    history = [json.loads(line) for line in (profile.runtime / "supervisor.log.jsonl").read_text().splitlines()]
    assert [(h["generation"], h["event"]) for h in history] == [
        (1, "ready"),
        (1, "exited"),
        (2, "boot-failed"),
        (2, "rolled-back"),
        (3, "ready"),
        (3, "exited"),
    ]
    assert history[1]["code"] == 75
    assert "boom during app/ready" in history[2]["error"]

    gen1 = json.loads((markers / "gen-1.json").read_text())
    gen3 = json.loads((markers / "gen-3.json").read_text())
    assert gen1["state"] is None
    assert gen3["state"]["resume"] == ["s-1"]
    assert gen3["state"]["rollback"]["failed_generation"] == 2
    assert "boom" not in json.dumps(profile.patch_ops_raw())  # broken entry: rolled back
    assert not (markers / "gen-2.json").exists()
    # Hand-off: committed by generation 3; nothing left for a later start.
    assert not (profile.runtime / "resume.json").exists()
    assert not (profile.runtime / "rollback.json").exists()
