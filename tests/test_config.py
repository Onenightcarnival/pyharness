from __future__ import annotations

import pytest

from pyxis_harness import Profile
from pyxis_harness.config import ConfigError, compose, interpolate, parse_ops, tree_to_data


def layers(*named):
    return [(name, parse_ops(ops, name)) for name, ops in named]


def test_layers_insert_replace_merge_remove():
    tree, warnings = compose(
        layers(
            (
                "bundle:a",
                [{"id": "a", "name": "p-a", "config": {"x": 1, "nested": {"k": 1}}}, {"id": "b", "name": "p-b"}],
            ),
            (
                "bundle:b",
                [{"id": "c", "name": "p-c", "before": "b"}, {"id": "g", "children": [{"id": "g1", "name": "p-g1"}]}],
            ),
            (
                "profile",
                [
                    {"id": "a", "config": {"nested": {"j": 2}}, "merge": True},
                    {"id": "b", "disabled": True},
                    {"id": "g2", "name": "p-g2", "parent": "g"},
                    {"id": "c", "remove": True},
                    {"id": "ghost", "disabled": True},
                ],
            ),
        )
    )
    data = tree_to_data(tree)
    assert [e["id"] for e in data] == ["a", "b", "g"]
    assert data[0]["config"] == {"x": 1, "nested": {"k": 1, "j": 2}}
    assert data[1]["disabled"] is True
    assert [c["id"] for c in data[2]["children"]] == ["g1", "g2"]
    assert any("ghost" in w for w in warnings)


def test_config_is_replaced_without_merge():
    tree, _ = compose(
        layers(("a", [{"id": "a", "name": "p", "config": {"x": 1, "y": 2}}]), ("b", [{"id": "a", "config": {"y": 3}}]))
    )
    assert tree[0].config == {"y": 3}


def test_duplicate_ids_rejected():
    with pytest.raises(ConfigError):
        compose(
            layers(
                ("a", [{"id": "g", "children": [{"id": "x", "name": "p"}]}, {"id": "y", "name": "p"}]),
                ("b", [{"id": "y", "children": [{"id": "x", "name": "p"}]}]),
            )
        )


def test_unknown_fields_rejected():
    with pytest.raises(ConfigError):
        parse_ops([{"id": "a", "nmae": "typo"}], "t")


def test_interpolation(monkeypatch):
    monkeypatch.setenv("PYH_T_SET", "value")
    monkeypatch.delenv("PYH_T_UNSET", raising=False)
    vars_ = {"cwd": "/w", "data_dir": "/d"}
    assert interpolate("${env:PYH_T_SET}", vars_) == "value"
    assert interpolate("${env:PYH_T_UNSET}", vars_) is None
    assert interpolate("${env:PYH_T_UNSET:-fallback}", vars_) == "fallback"
    assert interpolate("${env:PYH_T_UNSET:-${cwd}}/x", vars_) == "/w/x"
    assert interpolate({"p": ["${data_dir}/a.db"]}, vars_) == {"p": ["/d/a.db"]}
    with pytest.raises(ConfigError):
        interpolate("${nope}", vars_)
    # A credential template stays as written: alone, inside text, inside a default.
    assert interpolate("${credential:GH_TOKEN}", vars_) == "${credential:GH_TOKEN}"
    assert interpolate({"h": ["Bearer ${credential:GH_TOKEN} in ${cwd}"]}, vars_) == {
        "h": ["Bearer ${credential:GH_TOKEN} in /w"]
    }
    assert interpolate("${env:PYH_T_UNSET:-${credential:GH_TOKEN}}", vars_) == "${credential:GH_TOKEN}"
    # Substituted values: literal, never re-scanned. No placeholder limit.
    monkeypatch.setenv("PYH_T_SET", "${cwd}")
    assert interpolate("${env:PYH_T_SET}", vars_) == "${cwd}"
    assert interpolate("${cwd}" * 100, vars_) == "/w" * 100


def test_a_manifest_with_retired_bundle_names_composes_the_same_harness(tmp_path):
    current = Profile.init("web", home=str(tmp_path / "current"))
    old = Profile.init("web", home=str(tmp_path / "old"))
    # Written while the built-in list was four bundles: creator on, the web preset off.
    old.save_manifest({"title": "Web", "bundles": ["base", "creator"], "disabled": ["web"]})
    assert old.bundles() == ["base"]
    assert old.retired_ops() == [
        {"id": "agent-loop", "merge": True, "config": {"default_preset": "creator"}},
        {"id": "web-tools", "merge": True, "config": {"agent_tools": False}},
    ]
    tree = {entry["id"]: entry for entry in tree_to_data(old.compose().tree)}
    assert [e["id"] for e in tree_to_data(current.compose().tree)] == list(tree)
    assert tree["agent-loop"]["config"]["default_preset"] == "creator"
    assert tree["web-tools"]["config"] == {"agent_tools": False}
    # The names stay out of the listing and of the switch.
    assert [b["bundle"] for b in old.installed_bundles()] == ["base"] and old.shipped_bundles() == ["base"]
    with pytest.raises(ConfigError, match="ships with the harness"):
        old.set_bundle_enabled("base", False)
    assert old.set_bundle_enabled("base", True) is False


def test_the_creator_template_is_the_base_bundle_with_a_default_preset(tmp_path):
    profile = Profile.init("creator", template="creator", home=str(tmp_path))
    tree = {entry["id"]: entry for entry in tree_to_data(profile.compose().tree)}
    assert profile.bundles() == ["base"] and tree["agent-loop"]["config"]["default_preset"] == "creator"
    assert Profile.init("empty", template="empty", home=str(tmp_path)).compose().tree == []
