"""
Tests for JSON Merge Patch (RFC 7396) helpers.
"""
from homer.cluster.merge_patch import merge_patch, diff_patch


def test_merge_empty_patch():
    target = {"a": 1, "b": {"c": 2}}
    assert merge_patch(target, {}) == target


def test_merge_add_key():
    assert merge_patch({"a": 1}, {"b": 2}) == {"a": 1, "b": 2}


def test_merge_override_value():
    assert merge_patch({"a": 1}, {"a": 2}) == {"a": 2}


def test_merge_delete_key():
    assert merge_patch({"a": 1, "b": 2}, {"a": None}) == {"b": 2}


def test_merge_nested():
    target = {"a": {"b": 1, "c": 2}}
    patch = {"a": {"c": 3, "d": 4}}
    assert merge_patch(target, patch) == {"a": {"b": 1, "c": 3, "d": 4}}


def test_merge_two_disjoint_patches():
    """
    Two nodes editing different keys -> both survive.
    """
    start = {"app": {"name": "Homer", "version": "1.0.0"},
             "logging": {"level": "INFO"}}

    node_a = {"app": {"version": "1.0.1"}}
    node_b = {"logging": {"level": "DEBUG"}}

    after_a = merge_patch(start, node_a)
    after_b = merge_patch(after_a, node_b)

    assert after_b == {
        "app": {"name": "Homer", "version": "1.0.1"},
        "logging": {"level": "DEBUG"},
    }


def test_merge_patch_on_non_dict_returns_patch():
    assert merge_patch(42, {"a": 1}) == {"a": 1}
    assert merge_patch({"a": 1}, 42) == 42
    assert merge_patch({"a": 1}, None) is None


def test_diff_patch_simple():
    before = {"a": 1, "b": 2}
    after = {"a": 1, "b": 3, "c": 4}
    assert diff_patch(before, after) == {"b": 3, "c": 4}


def test_diff_patch_delete():
    before = {"a": 1, "b": 2}
    after = {"a": 1}
    assert diff_patch(before, after) == {"b": None}


def test_diff_patch_nested():
    before = {"a": {"x": 1, "y": 2}}
    after = {"a": {"x": 1, "y": 3}}
    assert diff_patch(before, after) == {"a": {"y": 3}}


def test_diff_patch_no_change():
    assert diff_patch({"a": 1}, {"a": 1}) == {}


def test_diff_patch_roundtrip():
    before = {"a": {"x": 1, "y": 2}, "b": [1, 2]}
    after = {"a": {"x": 1, "y": 5}, "b": [1, 2, 3]}
    patch = diff_patch(before, after)
    assert merge_patch(before, patch) == after
