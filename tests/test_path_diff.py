import pytest

from chronon.core.diff import compare_content, structural_changes
from chronon.core.errors import PathError
from chronon.core.path import get_value, parse_path, set_value, unset_value


def test_path_parser_supports_lists_and_quoted_keys() -> None:
    assert parse_path("servers.hosts[0].name") == ["servers", "hosts", 0, "name"]
    assert parse_path("servers['api.v2'].port") == ["servers", "api.v2", "port"]


def test_path_get_set_unset_and_mapping_creation() -> None:
    document = {"servers": {"hosts": [{"name": "one"}]}}
    assert get_value(document, "servers.hosts[0].name") == "one"
    updated = set_value(document, "servers.web.port", 9090)
    assert updated["servers"]["web"]["port"] == 9090
    removed = unset_value(updated, "servers.hosts[0].name")
    assert removed["servers"]["hosts"][0] == {}
    assert document == {"servers": {"hosts": [{"name": "one"}]}}


def test_list_indices_are_not_auto_extended() -> None:
    with pytest.raises(PathError):
        set_value({"items": []}, "items[1]", "x")


def test_structural_diff_ignores_mapping_order() -> None:
    old = "a: 1\nb: 2\n"
    new = "b: 2\na: 1\n"
    result = compare_content(old, new, "config.yml")
    assert result["changes"] == []


def test_structural_diff_reports_reusable_paths() -> None:
    old = {"servers": {"api.v2": {"port": 8080}, "hosts": ["a"]}}
    new = {"servers": {"api.v2": {"port": 9090}, "hosts": ["a", "b"]}}
    changes = structural_changes(old, new)
    assert changes == [
        {"op": "modified", "path": "servers['api.v2'].port", "old": 8080, "new": 9090},
        {"op": "added", "path": "servers.hosts[1]", "new": "b"},
    ]


def test_text_diff_fallback() -> None:
    result = compare_content("one\n", "two\n", "notes.txt")
    assert "-one" in result["text"]
    assert "+two" in result["text"]
