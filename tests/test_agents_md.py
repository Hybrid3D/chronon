from pathlib import Path

import pytest
from typer.testing import CliRunner

from chronon.api.operations import (
    init_repository,
    write_agent_instructions,
)
from chronon.cli import app
from chronon.core.docs import (
    BEGIN_MARKER,
    END_MARKER,
    ensure_agents_md,
    render_vault_section,
)
from chronon.core.errors import InvalidArgument

runner = CliRunner()


def test_ensure_agents_md_creates_file(tmp_path: Path) -> None:
    init_repository(tmp_path)
    result = ensure_agents_md(tmp_path)
    assert result == {
        "path": str(tmp_path / "CHRONON.md"),
        "created": True,
        "updated": True,
    }
    content = (tmp_path / "CHRONON.md").read_text(encoding="utf-8")
    assert content.startswith("# CHRONON.md\n")
    assert BEGIN_MARKER in content
    assert END_MARKER in content
    assert "chronon add <path>" in content
    assert "chronon is plumbing" in content.lower()
    assert "never narrate chronon commands" in content.lower()
    assert "chronon --vault <vault> ls ." in content
    assert "Do not guess which named vault to use" in content
    assert "working_revision" in content
    assert "revision_conflict" in content


def test_vault_template_is_specialized_for_one_vault() -> None:
    content = render_vault_section("knowledge")

    assert "registered Chronon vault **`knowledge`**" in content
    assert "chronon --vault knowledge ls ." in content
    assert "chronon --vault knowledge read <path>" in content
    assert "chronon --vault knowledge write <path>" in content
    assert "direct filesystem tools" in content
    assert "<vault>" not in content


def test_ensure_agents_md_custom_filename(tmp_path: Path) -> None:
    init_repository(tmp_path)
    result = ensure_agents_md(tmp_path, "AGENTS.md")
    assert result["path"] == str(tmp_path / "AGENTS.md")
    content = (tmp_path / "AGENTS.md").read_text(encoding="utf-8")
    assert content.startswith("# AGENTS.md\n")
    assert BEGIN_MARKER in content
    assert not (tmp_path / "CHRONON.md").exists()


def test_ensure_agents_md_rejects_path_as_filename(tmp_path: Path) -> None:
    init_repository(tmp_path)
    with pytest.raises(InvalidArgument):
        ensure_agents_md(tmp_path, "sub/AGENTS.md")


def test_ensure_agents_md_is_idempotent(tmp_path: Path) -> None:
    init_repository(tmp_path)
    ensure_agents_md(tmp_path)
    before = (tmp_path / "CHRONON.md").read_text(encoding="utf-8")

    result = ensure_agents_md(tmp_path)

    assert result["created"] is False
    assert result["updated"] is False
    assert (tmp_path / "CHRONON.md").read_text(encoding="utf-8") == before


def test_ensure_agents_md_appends_to_existing_file_without_marker(
    tmp_path: Path,
) -> None:
    init_repository(tmp_path)
    (tmp_path / "CHRONON.md").write_text(
        "# My rules\n\nAlways ask first.\n", encoding="utf-8"
    )

    result = ensure_agents_md(tmp_path)

    assert result == {
        "path": str(tmp_path / "CHRONON.md"),
        "created": False,
        "updated": True,
    }
    content = (tmp_path / "CHRONON.md").read_text(encoding="utf-8")
    assert content.startswith("# My rules\n\nAlways ask first.\n")
    assert BEGIN_MARKER in content


def test_ensure_agents_md_preserves_content_outside_markers_on_refresh(
    tmp_path: Path,
) -> None:
    init_repository(tmp_path)
    ensure_agents_md(tmp_path)
    path = tmp_path / "CHRONON.md"
    original = path.read_text(encoding="utf-8")
    edited = "# My Notes\n\nDo not delete this line.\n\n" + original
    path.write_text(edited, encoding="utf-8")

    result = ensure_agents_md(tmp_path)

    assert result["updated"] is False  # section content unchanged, so no rewrite
    content = path.read_text(encoding="utf-8")
    assert content.startswith("# My Notes\n\nDo not delete this line.\n\n")
    assert content.count(BEGIN_MARKER) == 1


@pytest.mark.parametrize(
    "content",
    [
        f"{BEGIN_MARKER}\nmissing end\n",
        f"{END_MARKER}\nwrong order\n{BEGIN_MARKER}\n",
        f"{BEGIN_MARKER}\none\n{END_MARKER}\n{BEGIN_MARKER}\ntwo\n{END_MARKER}\n",
    ],
)
def test_ensure_agents_md_rejects_malformed_markers(
    tmp_path: Path, content: str
) -> None:
    init_repository(tmp_path)
    path = tmp_path / "CHRONON.md"
    path.write_text(content, encoding="utf-8")

    with pytest.raises(InvalidArgument, match="malformed chronon markers"):
        ensure_agents_md(tmp_path)

    assert path.read_text(encoding="utf-8") == content


def test_write_agent_instructions_targets_external_directory(tmp_path: Path) -> None:
    destination = tmp_path / "workspace"
    destination.mkdir()

    result = write_agent_instructions(destination)

    assert result["created"] is True
    assert result["path"] == str(destination / "CHRONON.md")


def test_write_agent_instructions_validates_and_describes_vault(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("CHRONON_CONFIG_HOME", str(tmp_path / "config"))
    vault = tmp_path / "vault"
    destination = tmp_path / "workspace"
    destination.mkdir()
    init_repository(vault, register_vault="knowledge")

    result = write_agent_instructions(destination, vault="knowledge")

    assert result["path"] == str(destination / "CHRONON.md")
    content = (destination / "CHRONON.md").read_text(encoding="utf-8")
    assert "chronon --vault knowledge ls ." in content
    assert not (vault / "CHRONON.md").exists()


# ── CLI ──────────────────────────────────────────────────────────────────


def test_cli_agents_md_command(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)

    created = runner.invoke(app, ["agents-md"])
    assert created.exit_code == 0
    assert "Created" in created.output
    assert (tmp_path / "CHRONON.md").is_file()

    unchanged = runner.invoke(app, ["agents-md"])
    assert unchanged.exit_code == 0
    assert "already up to date" in unchanged.output


def test_cli_agents_md_command_custom_path(tmp_path: Path, monkeypatch) -> None:
    destination = tmp_path / "external-project"
    destination.mkdir()
    monkeypatch.chdir(tmp_path)

    created = runner.invoke(app, ["agents-md", str(destination)])
    assert created.exit_code == 0, created.output
    assert "Created" in created.output
    assert (destination / "CHRONON.md").is_file()
    assert not (destination / "AGENTS.md").exists()
    assert not (tmp_path / "CHRONON.md").exists()


def test_cli_agents_md_vault_option_writes_to_current_directory(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("CHRONON_CONFIG_HOME", str(tmp_path / "config"))
    root = tmp_path / "proj"
    assert runner.invoke(app, ["init", str(root), "--register", "mine"]).exit_code == 0

    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)

    result = runner.invoke(app, ["agents-md", "--vault", "mine"])
    assert result.exit_code == 0, result.output
    assert (elsewhere / "CHRONON.md").is_file()
    assert not (root / "CHRONON.md").exists()
    content = (elsewhere / "CHRONON.md").read_text(encoding="utf-8")
    assert "chronon --vault mine ls ." in content
    assert "chronon --vault mine read <path>" in content


def test_cli_agents_md_accepts_global_vault_option_and_custom_path(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("CHRONON_CONFIG_HOME", str(tmp_path / "config"))
    root = tmp_path / "proj"
    assert runner.invoke(app, ["init", str(root), "--register", "mine"]).exit_code == 0

    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    destination = tmp_path / "agent-project"
    destination.mkdir()
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(app, ["--vault", "mine", "agents-md", str(destination)])
    assert result.exit_code == 0, result.output
    assert (destination / "CHRONON.md").is_file()
    assert "chronon --vault mine" in (destination / "CHRONON.md").read_text(
        encoding="utf-8"
    )
