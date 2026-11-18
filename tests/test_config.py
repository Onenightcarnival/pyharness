from __future__ import annotations

import pytest

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
