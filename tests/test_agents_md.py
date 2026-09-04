from pathlib import Path

import pytest
from typer.testing import CliRunner

from chronon.api.operations import ChrononRepository, init_repository
from chronon.cli import app
from chronon.core.docs import BEGIN_MARKER, END_MARKER, ensure_agents_md
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
    assert "chronon --vault myvault status <path>" in content
    assert "chronon -v myvault diff <path>" in content
    assert "working_revision" in content
    assert "revision_conflict" in content


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


def test_repository_write_agents_md(tmp_path: Path) -> None:
    init_repository(tmp_path)
    repo = ChrononRepository(tmp_path)
    result = repo.write_agents_md()
    assert result["created"] is True
    assert result["path"] == str(tmp_path / "CHRONON.md")


def test_repository_write_agents_md_custom_filename(tmp_path: Path) -> None:
    init_repository(tmp_path)
    result = ChrononRepository(tmp_path).write_agents_md("AGENTS.md")
    assert result["path"] == str(tmp_path / "AGENTS.md")


# ── CLI ──────────────────────────────────────────────────────────────────


def test_cli_init_with_agents_md_flag(tmp_path: Path) -> None:
    result = runner.invoke(app, ["init", str(tmp_path), "--agents-md", "--json"])
    assert result.exit_code == 0, result.output
    assert (tmp_path / "CHRONON.md").is_file()


def test_cli_init_with_agents_md_file(tmp_path: Path) -> None:
    result = runner.invoke(
        app, ["init", str(tmp_path), "--agents-md-file", "AGENTS.md", "--json"]
    )
    assert result.exit_code == 0, result.output
    assert (tmp_path / "AGENTS.md").is_file()
    assert not (tmp_path / "CHRONON.md").exists()


def test_cli_agents_md_command(tmp_path: Path, monkeypatch) -> None:
    assert runner.invoke(app, ["init", str(tmp_path)]).exit_code == 0
    monkeypatch.chdir(tmp_path)

    created = runner.invoke(app, ["agents-md"])
    assert created.exit_code == 0
    assert "Created" in created.output
    assert (tmp_path / "CHRONON.md").is_file()

    unchanged = runner.invoke(app, ["agents-md"])
    assert unchanged.exit_code == 0
    assert "already up to date" in unchanged.output


def test_cli_agents_md_command_custom_filename(tmp_path: Path, monkeypatch) -> None:
    assert runner.invoke(app, ["init", str(tmp_path)]).exit_code == 0
    monkeypatch.chdir(tmp_path)

    created = runner.invoke(app, ["agents-md", "AGENTS.md"])
    assert created.exit_code == 0, created.output
    assert "Created" in created.output
    assert (tmp_path / "AGENTS.md").is_file()
    assert not (tmp_path / "CHRONON.md").exists()


def test_cli_agents_md_works_via_vault_from_unrelated_cwd(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("CHRONON_CONFIG_HOME", str(tmp_path / "config"))
    root = tmp_path / "proj"
    assert runner.invoke(app, ["init", str(root), "--register", "mine"]).exit_code == 0

    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)

    result = runner.invoke(app, ["--vault", "mine", "agents-md"])
    assert result.exit_code == 0, result.output
    assert (root / "CHRONON.md").is_file()


def test_cli_agents_md_custom_filename_via_vault(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("CHRONON_CONFIG_HOME", str(tmp_path / "config"))
    root = tmp_path / "proj"
    assert runner.invoke(app, ["init", str(root), "--register", "mine"]).exit_code == 0

    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)

    result = runner.invoke(app, ["--vault", "mine", "agents-md", "AGENTS.md"])
    assert result.exit_code == 0, result.output
    assert (root / "AGENTS.md").is_file()
