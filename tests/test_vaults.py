import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from chronon.api.operations import ChrononRepository, init_repository
from chronon.cli import _splice_positional_vault, app, main
from chronon.core import vaults
from chronon.core.errors import ChrononError, FileError, InvalidArgument

runner = CliRunner()


@pytest.fixture(autouse=True)
def isolated_registry(tmp_path: Path, monkeypatch) -> None:
    """Every test gets its own vault registry, never the real user's."""
    monkeypatch.setenv("CHRONON_CONFIG_HOME", str(tmp_path / "config"))


# ── core/vaults.py ──────────────────────────────────────────────────────────


def test_add_vault_requires_an_initialized_repository(tmp_path: Path) -> None:
    with pytest.raises(FileError):
        vaults.add_vault("mine", tmp_path / "not-a-repo")


def test_add_list_remove_round_trip(tmp_path: Path) -> None:
    root = tmp_path / "proj"
    init_repository(root)

    added = vaults.add_vault("mine", root)
    assert added == {"name": "mine", "path": str(root.resolve()), "created": True}
    assert vaults.list_vaults() == {"mine": str(root.resolve())}
    assert vaults.resolve_vault("mine") == root.resolve()

    # re-adding the same name updates the path instead of erroring
    again = vaults.add_vault("mine", root)
    assert again["created"] is False

    removed = vaults.remove_vault("mine")
    assert removed == {"name": "mine", "removed": True}
    assert vaults.list_vaults() == {}


def test_resolve_unknown_vault_raises(tmp_path: Path) -> None:
    with pytest.raises(InvalidArgument):
        vaults.resolve_vault("nope")


def test_remove_unknown_vault_raises(tmp_path: Path) -> None:
    with pytest.raises(InvalidArgument):
        vaults.remove_vault("nope")


def test_invalid_vault_name_rejected(tmp_path: Path) -> None:
    root = tmp_path / "proj"
    init_repository(root)
    with pytest.raises(InvalidArgument):
        vaults.add_vault("has a space", root)


def test_registry_survives_across_processes(tmp_path: Path) -> None:
    """The registry is a plain file, not process state — a second 'process'
    (here: a second call chain with a fresh Store) must see the same vaults."""
    root = tmp_path / "proj"
    init_repository(root)
    vaults.add_vault("mine", root)
    assert vaults.resolve_vault("mine") == root.resolve()
    # simulate a fresh process re-reading the registry from disk
    assert vaults.list_vaults()["mine"] == str(root.resolve())


# ── ChrononRepository(vault=...) resolves without touching cwd ─────────────


def test_repository_resolves_root_via_vault(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "proj"
    init_repository(root)
    vaults.add_vault("mine", root)
    (root / "docs.yml").write_text("value: 1\n", encoding="utf-8")

    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)

    repo = ChrononRepository(vault="mine")
    assert repo.root == root.resolve()
    added = repo.add("docs.yml")
    assert added["resource"] == "docs.yml"


def test_repository_unknown_vault_raises(tmp_path: Path) -> None:
    with pytest.raises(ChrononError):
        ChrononRepository(vault="nope")


# ── CLI: `chronon add-vault` / `list-vaults` / `remove-vault` ──────────────


def test_cli_add_list_remove_vault(tmp_path: Path) -> None:
    root = tmp_path / "proj"
    assert runner.invoke(app, ["init", str(root)]).exit_code == 0

    add = runner.invoke(app, ["add-vault", "mine", str(root), "--json"])
    assert add.exit_code == 0, add.output
    assert json.loads(add.output)["name"] == "mine"

    listing = runner.invoke(app, ["list-vaults", "--json"])
    assert json.loads(listing.output)["vaults"] == [
        {"name": "mine", "path": str(root.resolve())}
    ]

    remove = runner.invoke(app, ["remove-vault", "mine", "--json"])
    assert remove.exit_code == 0, remove.output
    assert runner.invoke(
        app, ["list-vaults", "--json"]
    ).output.strip() == json.dumps({"vaults": []}, ensure_ascii=False, indent=2).strip()


def test_cli_init_directory_matching_a_vault_name_is_not_spliced(
    tmp_path: Path, monkeypatch
) -> None:
    """`init` takes no --vault, so `_command_accepts_vault` must exclude it —
    a bare DIRECTORY argument that happens to match a registered vault name
    (here also literally "proj") must be treated as a directory, not spliced
    into `--vault proj` (which `init` doesn't understand and would reject)."""
    other_root = tmp_path / "other"
    runner.invoke(app, ["init", str(other_root), "--register", "proj"])

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.argv", ["chronon", "init", "proj"])

    with pytest.raises(SystemExit) as excinfo:
        main()
    assert excinfo.value.code in (0, None)
    assert (tmp_path / "proj" / ".chronon" / "config.toml").is_file()


def test_cli_init_register_registers_a_vault_in_one_step(tmp_path: Path) -> None:
    root = tmp_path / "proj"
    result = runner.invoke(app, ["init", str(root), "--register", "mine", "--json"])
    assert result.exit_code == 0, result.output
    assert vaults.resolve_vault("mine") == root.resolve()


# ── CLI: --vault works from any cwd, without positional shorthand ──────────


def test_cli_explicit_vault_flag_works_from_unrelated_cwd(
    tmp_path: Path, monkeypatch
) -> None:
    root = tmp_path / "proj"
    assert runner.invoke(app, ["init", str(root), "--register", "mine"]).exit_code == 0
    (root / "docs.yml").write_text("value: 1\n", encoding="utf-8")

    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)

    assert runner.invoke(app, ["add", "docs.yml", "--vault", "mine"]).exit_code == 0
    rev = json.loads(
        runner.invoke(app, ["read", "docs.yml", "--vault", "mine", "--json"]).output
    )["working_revision"]
    committed = runner.invoke(
        app,
        ["commit", "docs.yml", "--vault", "mine", "-m", "initial", "--if-match", rev],
    )
    assert committed.exit_code == 0, committed.output

    status = runner.invoke(app, ["status", "docs.yml", "--vault", "mine", "--json"])
    assert json.loads(status.output)["state"] == "clean"


# ── positional vault shorthand: `chronon <command> <vault> <resource>` ─────


def test_splice_positional_vault_rewrites_registered_name(
    tmp_path: Path,
) -> None:
    root = tmp_path / "proj"
    init_repository(root)
    vaults.add_vault("mine", root)

    argv = ["diff", "mine", "docs.yml", "--from", "7d ago"]
    spliced = _splice_positional_vault(argv, slot=1)
    assert spliced == ["diff", "docs.yml", "--from", "7d ago", "--vault", "mine"]


def test_splice_positional_vault_leaves_unregistered_tokens_alone(
    tmp_path: Path,
) -> None:
    argv = ["diff", "docs.yml", "--from", "7d ago"]
    assert _splice_positional_vault(argv, slot=1) == argv


def test_splice_positional_vault_ignores_flags_in_slot(tmp_path: Path) -> None:
    argv = ["diff", "--json", "docs.yml"]
    assert _splice_positional_vault(argv, slot=1) == argv


def test_cli_main_accepts_positional_vault_shorthand(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """`chronon <command> <vault> <resource>` must work through the real
    entry point (main()), from a cwd that has nothing to do with the vault."""
    root = tmp_path / "proj"
    assert runner.invoke(app, ["init", str(root), "--register", "mine"]).exit_code == 0
    (root / "docs.yml").write_text("value: 1\n", encoding="utf-8")

    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    monkeypatch.setattr("sys.argv", ["chronon", "add", "mine", "docs.yml"])

    with pytest.raises(SystemExit) as excinfo:
        main()
    assert excinfo.value.code in (0, None)
    assert "docs.yml" in capsys.readouterr().out
