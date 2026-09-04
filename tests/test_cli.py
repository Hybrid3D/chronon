import json
import re
from pathlib import Path

from typer.testing import CliRunner

from chronon import __version__
from chronon.cli import app

runner = CliRunner()


def test_global_version_options_replace_version_command() -> None:
    for option in ("--version", "-V"):
        result = runner.invoke(app, [option])
        assert result.exit_code == 0, result.output
        assert result.output == f"chronon {__version__}\n"

    removed = runner.invoke(app, ["version"])
    assert removed.exit_code != 0


def _working_revision(resource: str) -> str:
    result = runner.invoke(app, ["read", resource, "--json"])
    assert result.exit_code == 0, result.output
    return json.loads(result.output)["working_revision"]


def test_cli_end_to_end(tmp_path: Path, monkeypatch) -> None:
    result = runner.invoke(app, ["init", str(tmp_path), "--json"])
    assert result.exit_code == 0, result.output
    (tmp_path / "docs.yml").write_text("value: 1\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    assert runner.invoke(app, ["add", "docs.yml"]).exit_code == 0
    committed = runner.invoke(
        app,
        [
            "commit",
            "docs.yml",
            "-m",
            "initial",
            "--if-match",
            _working_revision("docs.yml"),
        ],
    )
    assert committed.exit_code == 0, committed.output
    changed = runner.invoke(
        app,
        ["set", "docs.yml", "--path", "value", "--value", "2", "--type", "int"],
    )
    assert changed.exit_code == 0, changed.output

    diff = runner.invoke(app, ["diff", "docs.yml", "--json"])
    assert diff.exit_code == 0, diff.output
    assert json.loads(diff.output)["changes"][0]["new"] == 2

    logged = runner.invoke(app, ["log", "docs.yml", "--json"])
    assert json.loads(logged.output)["commits"][0]["message"] == "initial"


def test_cli_auto_init_fails_clearly(tmp_path: Path) -> None:
    result = runner.invoke(app, ["init", str(tmp_path), "--mode", "auto", "--json"])
    assert result.exit_code == 4
    assert json.loads(result.output)["error"] == "not_implemented"


def test_clean_text_diff_says_no_changes(tmp_path: Path, monkeypatch) -> None:
    assert runner.invoke(app, ["init", str(tmp_path)]).exit_code == 0
    (tmp_path / "notes.md").write_text("# Notes\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    assert runner.invoke(app, ["add", "notes.md"]).exit_code == 0
    assert (
        runner.invoke(
            app,
            [
                "commit",
                "notes.md",
                "-m",
                "initial",
                "--if-match",
                _working_revision("notes.md"),
            ],
        ).exit_code
        == 0
    )

    result = runner.invoke(app, ["diff", "notes.md"])
    assert result.exit_code == 0
    assert result.output.strip() == "No changes"

    status = runner.invoke(app, ["status", "notes.md"])
    assert status.exit_code == 0
    assert "commits=1" in status.output
    assert "last=" in status.output


def test_main_ls_and_read_commands(tmp_path: Path, monkeypatch) -> None:
    assert runner.invoke(app, ["init", str(tmp_path)]).exit_code == 0
    (tmp_path / "empty.txt").write_text("", encoding="utf-8")
    (tmp_path / "notes.txt").write_text("first\nsecond\n", encoding="utf-8")
    (tmp_path / "private.txt").write_text("not tracked\n", encoding="utf-8")
    (tmp_path / "nested").mkdir()
    (tmp_path / "nested" / "tracked.txt").write_text("nested\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    assert (
        runner.invoke(
            app, ["add", "empty.txt", "notes.txt", "nested/tracked.txt"]
        ).exit_code
        == 0
    )

    listed = runner.invoke(app, ["ls", "."])
    assert listed.exit_code == 0, listed.output
    assert listed.output == "empty.txt\nnested/\nnotes.txt\n"

    nested = runner.invoke(app, ["ls", "nested", "--json"])
    assert nested.exit_code == 0, nested.output
    assert json.loads(nested.output)["entries"] == [
        {"name": "tracked.txt", "path": "nested/tracked.txt", "type": "file"}
    ]

    content = runner.invoke(app, ["read", "notes.txt"])
    assert content.exit_code == 0, content.output
    assert content.output == "first\nsecond\n"
    assert runner.invoke(app, ["read", "empty.txt"]).output == ""

    assert (
        runner.invoke(
            app,
            [
                "commit",
                "notes.txt",
                "-m",
                "initial",
                "--if-match",
                _working_revision("notes.txt"),
            ],
        ).exit_code
        == 0
    )
    assert (
        runner.invoke(
            app, ["write", "notes.txt", "--content", "changed\n", "--scratch"]
        ).exit_code
        == 0
    )
    historical = runner.invoke(app, ["read", "notes.txt", "--at", "latest"])
    assert historical.exit_code == 0, historical.output
    assert historical.output == "first\nsecond\n"


def test_main_commands_use_vault_relative_paths_from_nested_cwd(
    tmp_path: Path, monkeypatch
) -> None:
    assert runner.invoke(app, ["init", str(tmp_path)]).exit_code == 0
    nested = tmp_path / "nested"
    nested.mkdir()
    (nested / "notes.txt").write_text("nested content\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    assert runner.invoke(app, ["add", "nested/notes.txt"]).exit_code == 0

    monkeypatch.chdir(nested)
    assert runner.invoke(app, ["ls", "nested"]).output == "notes.txt\n"
    assert runner.invoke(app, ["read", "nested/notes.txt"]).output == "nested content\n"


def test_main_commands_use_registered_vault_outside_cwd(
    tmp_path: Path, monkeypatch
) -> None:
    vault = tmp_path / "vault"
    outside = tmp_path / "outside"
    outside.mkdir()
    monkeypatch.setenv("CHRONON_CONFIG_HOME", str(tmp_path / "config"))
    assert (
        runner.invoke(app, ["init", str(vault), "--register", "knowledge"]).exit_code
        == 0
    )
    (vault / "notes.txt").write_text("vault content\n", encoding="utf-8")
    monkeypatch.chdir(vault)
    assert runner.invoke(app, ["add", "notes.txt"]).exit_code == 0

    monkeypatch.chdir(outside)
    listed = runner.invoke(app, ["--vault", "knowledge", "ls", "."])
    assert listed.exit_code == 0, listed.output
    assert listed.output == "notes.txt\n"
    content = runner.invoke(app, ["--vault", "knowledge", "read", "notes.txt"])
    assert content.exit_code == 0, content.output
    assert content.output == "vault content\n"


def test_main_write_creates_and_updates_in_registered_vault(
    tmp_path: Path, monkeypatch
) -> None:
    vault = tmp_path / "vault"
    outside = tmp_path / "outside"
    outside.mkdir()
    monkeypatch.setenv("CHRONON_CONFIG_HOME", str(tmp_path / "config"))
    assert (
        runner.invoke(app, ["init", str(vault), "--register", "knowledge"]).exit_code
        == 0
    )
    monkeypatch.chdir(outside)
    resource = "nested/notes.txt"
    vault_args = ["--vault", "knowledge"]

    created = runner.invoke(
        app,
        [*vault_args, "write", resource, "--stdin", "--scratch", "--json"],
        input="created through chronon\n",
    )
    assert created.exit_code == 0, created.output
    created_result = json.loads(created.output)
    assert created_result["created"] is True
    assert (
        runner.invoke(app, [*vault_args, "read", resource]).output
        == "created through chronon\n"
    )
    assert runner.invoke(app, [*vault_args, "ls", "nested"]).output == "notes.txt\n"
    assert (
        runner.invoke(app, [*vault_args, "ls", "nested", "-l"]).output
        == "scratch     0  -                 notes.txt\n"
    )

    updated = runner.invoke(
        app,
        [
            *vault_args,
            "write",
            resource,
            "--content",
            "updated\n",
            "-m",
            "update notes",
            "--if-match",
            created_result["working_revision"],
            "--json",
        ],
    )
    assert updated.exit_code == 0, updated.output
    result = json.loads(updated.output)
    assert result["created"] is False
    assert result["committed"] is True
    assert runner.invoke(app, [*vault_args, "read", resource]).output == "updated\n"
    # timestamp is wall-clock at commit time, so match its shape, not its value
    assert re.fullmatch(
        r"clean       1  \d{4}-\d{2}-\d{2} \d{2}:\d{2}  notes\.txt\n",
        runner.invoke(app, [*vault_args, "ls", "nested", "-l"]).output,
    )

    stale = runner.invoke(
        app,
        [
            *vault_args,
            "write",
            resource,
            "--content",
            "stale overwrite\n",
            "--scratch",
            "--if-match",
            created_result["working_revision"],
            "--json",
        ],
    )
    assert stale.exit_code == 7
    assert json.loads(stale.output)["error"] == "revision_conflict"
    assert runner.invoke(app, [*vault_args, "read", resource]).output == "updated\n"


def test_main_write_refuses_ambiguous_or_untracked_existing_input(
    tmp_path: Path, monkeypatch
) -> None:
    vault = tmp_path / "vault"
    assert runner.invoke(app, ["init", str(vault)]).exit_code == 0
    existing = vault / "existing.txt"
    existing.write_text("original\n", encoding="utf-8")
    monkeypatch.chdir(vault)

    ambiguous = runner.invoke(
        app,
        ["write", "new.txt", "--content", "value", "--stdin"],
        input="other",
    )
    assert ambiguous.exit_code == 4

    missing_mode = runner.invoke(app, ["write", "new.txt", "--content", "value"])
    assert missing_mode.exit_code == 4
    assert "choose exactly one of --scratch or --message" in missing_mode.output

    ambiguous_mode = runner.invoke(
        app,
        [
            "write",
            "new.txt",
            "--content",
            "value",
            "--scratch",
            "-m",
            "also commit",
        ],
    )
    assert ambiguous_mode.exit_code == 4

    overwrite = runner.invoke(
        app, ["write", "existing.txt", "--content", "replacement\n", "--scratch"]
    )
    assert overwrite.exit_code == 3
    assert "refusing to overwrite an untracked path" in overwrite.output
    assert existing.read_text(encoding="utf-8") == "original\n"


def test_main_commit_commits_exact_scratch_in_registered_vault(
    tmp_path: Path, monkeypatch
) -> None:
    vault = tmp_path / "vault"
    outside = tmp_path / "outside"
    outside.mkdir()
    monkeypatch.setenv("CHRONON_CONFIG_HOME", str(tmp_path / "config"))
    assert (
        runner.invoke(app, ["init", str(vault), "--register", "knowledge"]).exit_code
        == 0
    )
    monkeypatch.chdir(outside)
    vault_args = ["--vault", "knowledge"]
    resource = "draft.txt"

    scratch = runner.invoke(
        app,
        [*vault_args, "write", resource, "--content", "draft\n", "--scratch", "--json"],
    )
    scratch_revision = json.loads(scratch.output)["working_revision"]
    committed = runner.invoke(
        app,
        [
            *vault_args,
            "commit",
            resource,
            "-m",
            "finish draft",
            "--if-match",
            scratch_revision,
            "--json",
        ],
    )

    assert committed.exit_code == 0, committed.output
    result = json.loads(committed.output)
    assert result["committed"] is True
    assert result["state"] == "clean"
    assert (
        runner.invoke(app, [*vault_args, "read", resource, "--at", "latest"]).output
        == "draft\n"
    )


def test_main_write_validation_errors_are_json_when_requested(
    tmp_path: Path,
) -> None:
    resource = tmp_path / "new.txt"
    result = runner.invoke(
        app,
        [
            "write",
            str(resource),
            "--content",
            "value",
            "--stdin",
            "--scratch",
            "--json",
        ],
        input="other",
    )

    assert result.exit_code == 4
    payload = json.loads(result.output)
    assert payload["error"] == "invalid_argument"
    assert "exactly one" in payload["message"]


def test_generic_cli_errors_are_json_when_requested(
    tmp_path: Path, monkeypatch
) -> None:
    assert runner.invoke(app, ["init", str(tmp_path)]).exit_code == 0
    resource = tmp_path / "config.json"
    resource.write_text('{"value": 1}\n', encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    assert runner.invoke(app, ["add", "config.json"]).exit_code == 0
    schema = tmp_path / "schema.json"
    schema.write_text("not json\n", encoding="utf-8")

    result = runner.invoke(
        app,
        ["schema-register", "config.json", "--file", str(schema), "--json"],
    )

    assert result.exit_code == 4
    assert json.loads(result.output)["error"] == "invalid_argument"
