import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from chronon.cli import app
from chronon.core.errors import InvalidArgument
from chronon.core.permissions import (
    CLAUDE_SETTINGS,
    EXCLUDED_COMMANDS,
    check_permissions,
    ensure_permissions,
    permission_rules,
)

runner = CliRunner()


def _settings(root: Path) -> dict:
    return json.loads((root / CLAUDE_SETTINGS).read_text(encoding="utf-8"))


def _allow(root: Path) -> list[str]:
    return _settings(root)["permissions"]["allow"]


def test_rules_cover_both_positions_of_the_vault_selector() -> None:
    rules = permission_rules("knowledge")

    # The generated guidance puts --vault before the subcommand, so a rule for
    # the bare form alone would never match what the agent actually runs.
    assert "Bash(chronon read:*)" in rules
    assert "Bash(chronon --vault knowledge read:*)" in rules


def test_rules_omit_the_vault_form_when_no_vault_is_selected() -> None:
    assert not any("--vault" in rule for rule in permission_rules())


def test_rules_never_include_unrecoverable_commands() -> None:
    rules = permission_rules("knowledge")

    for command in EXCLUDED_COMMANDS:
        assert not any(f" {command}:*)" in rule for rule in rules)


def test_read_only_rules_exclude_mutating_commands() -> None:
    rules = permission_rules("knowledge", write=False)

    assert "Bash(chronon read:*)" in rules
    assert "Bash(chronon write:*)" not in rules
    assert "Bash(chronon commit:*)" not in rules


def test_ensure_permissions_creates_the_settings_file(tmp_path: Path) -> None:
    result = ensure_permissions(tmp_path, vault="knowledge")

    assert result["created"] is True
    assert result["updated"] is True
    assert result["path"] == str(tmp_path / CLAUDE_SETTINGS)
    assert "Bash(chronon --vault knowledge write:*)" in _allow(tmp_path)


def test_ensure_permissions_preserves_unrelated_settings(tmp_path: Path) -> None:
    path = tmp_path / CLAUDE_SETTINGS
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(
            {
                "permissions": {"allow": ["Bash(ls:*)"], "ask": ["Bash(rm:*)"]},
                "env": {"KEEP": "me"},
            }
        ),
        encoding="utf-8",
    )

    ensure_permissions(tmp_path)

    settings = _settings(tmp_path)
    assert settings["env"] == {"KEEP": "me"}
    assert settings["permissions"]["ask"] == ["Bash(rm:*)"]
    assert settings["permissions"]["allow"][0] == "Bash(ls:*)"
    assert "Bash(chronon read:*)" in settings["permissions"]["allow"]


def test_ensure_permissions_never_overrides_a_deny_rule(tmp_path: Path) -> None:
    path = tmp_path / CLAUDE_SETTINGS
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps({"permissions": {"deny": ["Bash(chronon rollback:*)"]}}),
        encoding="utf-8",
    )

    result = ensure_permissions(tmp_path)

    assert result["skipped"] == ["Bash(chronon rollback:*)"]
    assert "Bash(chronon rollback:*)" not in _allow(tmp_path)
    assert "Bash(chronon commit:*)" in _allow(tmp_path)


def test_ensure_permissions_is_idempotent(tmp_path: Path) -> None:
    ensure_permissions(tmp_path, vault="knowledge")
    before = (tmp_path / CLAUDE_SETTINGS).read_text(encoding="utf-8")

    result = ensure_permissions(tmp_path, vault="knowledge")

    assert result["updated"] is False
    assert result["added"] == []
    assert (tmp_path / CLAUDE_SETTINGS).read_text(encoding="utf-8") == before


def test_ensure_permissions_rejects_invalid_json(tmp_path: Path) -> None:
    path = tmp_path / CLAUDE_SETTINGS
    path.parent.mkdir(parents=True)
    path.write_text("{not json", encoding="utf-8")

    with pytest.raises(InvalidArgument, match="not valid JSON"):
        ensure_permissions(tmp_path)


def test_ensure_permissions_rejects_a_non_array_allow(tmp_path: Path) -> None:
    path = tmp_path / CLAUDE_SETTINGS
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"permissions": {"allow": "everything"}}), "utf-8")

    with pytest.raises(InvalidArgument, match="must be an array"):
        ensure_permissions(tmp_path)


def test_check_permissions_writes_nothing(tmp_path: Path) -> None:
    result = check_permissions(tmp_path)

    assert result["current"] is False
    assert result["status"] == "missing"
    assert result["missing_rules"]
    assert not (tmp_path / ".claude").exists()


def test_check_permissions_reports_a_partial_allowlist_as_stale(
    tmp_path: Path,
) -> None:
    path = tmp_path / CLAUDE_SETTINGS
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps({"permissions": {"allow": ["Bash(chronon read:*)"]}}),
        encoding="utf-8",
    )

    result = check_permissions(tmp_path)

    assert result["status"] == "stale"
    assert "Bash(chronon commit:*)" in result["missing_rules"]


def test_check_permissions_reports_a_complete_allowlist(tmp_path: Path) -> None:
    ensure_permissions(tmp_path, vault="knowledge")

    assert check_permissions(tmp_path, vault="knowledge")["current"] is True


# ── CLI ──────────────────────────────────────────────────────────────────


def test_cli_agents_md_permissions_is_opt_in(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)

    assert runner.invoke(app, ["agent-setup"]).exit_code == 0
    assert not (tmp_path / ".claude").exists()

    result = runner.invoke(app, ["agent-setup", "--permissions"])

    assert result.exit_code == 0, result.output
    assert "chronon rules" in result.output
    assert "Bash(chronon read:*)" in _allow(tmp_path)


def test_cli_agents_md_check_includes_permissions(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    runner.invoke(app, ["agent-setup"])

    stale = runner.invoke(app, ["agent-setup", "--permissions", "--check"])
    assert stale.exit_code == 1
    assert "missing" in stale.output
    assert not (tmp_path / ".claude").exists()

    runner.invoke(app, ["agent-setup", "--permissions"])

    current = runner.invoke(app, ["agent-setup", "--permissions", "--check"])
    assert current.exit_code == 0, current.output


def test_cli_agents_md_check_ignores_permissions_unless_asked(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.chdir(tmp_path)
    runner.invoke(app, ["agent-setup"])

    result = runner.invoke(app, ["agent-setup", "--check"])

    assert result.exit_code == 0, result.output
    assert "settings.local.json" not in result.output
