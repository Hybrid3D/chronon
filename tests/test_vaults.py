import json
import multiprocessing
import sys
from pathlib import Path

import pytest
from click import unstyle
from typer.testing import CliRunner

from chronon.api.operations import ChrononRepository, init_repository, list_vaults
from chronon.cli import app, main
from chronon.core import vaults
from chronon.core.errors import ChrononError, FileError, InvalidArgument

runner = CliRunner()


def _add_vault_worker(name: str, root: str, start, result) -> None:
    """Process target kept importable for the Windows ``spawn`` start method."""
    start.wait()
    try:
        vaults.add_vault(name, root)
    except Exception as exc:  # pragma: no cover - asserted through the queue
        result.put((False, repr(exc)))
    else:
        result.put((True, name))


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

    # Re-adding the same name and path is idempotent.
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
    with pytest.raises(InvalidArgument):
        vaults.add_vault("looks-valid\n", root)
    with pytest.raises(InvalidArgument):
        vaults.set_vault_path("has a space", root)


def test_add_vault_cannot_replace_an_existing_path(tmp_path: Path) -> None:
    old_root, new_root = tmp_path / "old", tmp_path / "new"
    init_repository(old_root, register_vault="mine")
    init_repository(new_root)
    before = vaults.registry_path().read_bytes()

    with pytest.raises(InvalidArgument, match="already registered") as excinfo:
        vaults.add_vault("mine", new_root)

    assert "chronon admin set-vault-path mine PATH" in excinfo.value.details["hint"]
    assert str(old_root) not in str(excinfo.value.as_dict())
    assert vaults.registry_path().read_bytes() == before


def test_set_vault_path_preserves_other_registrations(tmp_path: Path) -> None:
    old_root, new_root = tmp_path / "old", tmp_path / "new"
    init_repository(old_root, register_vault="mine")
    init_repository(new_root, register_vault="other")
    (old_root / "old.txt").write_text("old content", encoding="utf-8")
    (new_root / "new.txt").write_text("new content", encoding="utf-8")

    result = vaults.set_vault_path("mine", new_root)

    assert result == {
        "name": "mine",
        "previous_path": str(old_root.resolve()),
        "path": str(new_root.resolve()),
        "updated": True,
    }
    assert vaults.list_vaults() == {
        "mine": str(new_root.resolve()),
        "other": str(new_root.resolve()),
    }
    assert (old_root / "old.txt").read_text(encoding="utf-8") == "old content"
    assert (new_root / "new.txt").read_text(encoding="utf-8") == "new content"
    assert not (new_root / "old.txt").exists()
    assert not (old_root / "new.txt").exists()


def test_set_vault_path_is_idempotent_with_relative_paths(
    tmp_path: Path, monkeypatch
) -> None:
    root = tmp_path / "repo"
    init_repository(root, register_vault="mine")
    monkeypatch.chdir(tmp_path)
    before = vaults.registry_path().read_bytes()
    modified_at = vaults.registry_path().stat().st_mtime_ns

    result = vaults.set_vault_path("mine", "./repo")

    assert result["updated"] is False
    assert result["path"] == result["previous_path"] == str(root.resolve())
    assert vaults.registry_path().read_bytes() == before
    assert vaults.registry_path().stat().st_mtime_ns == modified_at


@pytest.mark.parametrize("kind", ["missing", "directory", "file", "nested"])
def test_admin_set_vault_path_rejects_invalid_targets_without_changing_registry(
    tmp_path: Path, kind: str
) -> None:
    root = tmp_path / "repo"
    init_repository(root, register_vault="mine")
    target = tmp_path / "invalid"
    if kind == "directory":
        target.mkdir()
    elif kind == "file":
        target.write_text("not a repository", encoding="utf-8")
    elif kind == "nested":
        target = root / "nested"
        target.mkdir()
    before = vaults.registry_path().read_bytes()

    result = runner.invoke(
        app, ["admin", "set-vault-path", "mine", str(target), "--json"]
    )

    assert result.exit_code == 3, result.output
    assert json.loads(result.output)["error"] == "file_error"
    assert vaults.registry_path().read_bytes() == before
    if kind == "missing":
        assert not target.exists()


def test_admin_set_vault_path_requires_an_existing_registration(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    init_repository(root, register_vault="other")
    before = vaults.registry_path().read_bytes()

    result = runner.invoke(
        app, ["admin", "set-vault-path", "missing", str(root), "--json"]
    )

    assert result.exit_code == 4, result.output
    assert json.loads(result.output)["error"] == "invalid_argument"
    assert json.loads(result.output)["name"] == "missing"
    assert vaults.registry_path().read_bytes() == before


@pytest.mark.parametrize("json_output", [False, True])
def test_admin_set_vault_path_reconnects_a_moved_repository(
    tmp_path: Path, json_output: bool
) -> None:
    old_root, new_root = tmp_path / "old storage", tmp_path / "new storage"
    init_repository(old_root, register_vault="mine")
    resource = old_root / "notes.md"
    resource.write_text("remember this", encoding="utf-8")
    repository = ChrononRepository(vault="mine")
    repository.add("notes.md")
    repository.commit(
        "notes.md",
        "initial",
        expected_revision=repository.read("notes.md")["working_revision"],
    )
    history = repository.history("notes.md")
    old_root.rename(new_root)
    args = ["admin", "set-vault-path", "mine", str(new_root)]
    if json_output:
        args.append("--json")

    result = runner.invoke(app, args)

    assert result.exit_code == 0, result.output
    if json_output:
        assert json.loads(result.output) == {
            "name": "mine",
            "previous_path": str(old_root.resolve()),
            "path": str(new_root.resolve()),
            "updated": True,
        }
    else:
        assert (
            result.output
            == f"Updated vault mine: {old_root.resolve()} -> {new_root.resolve()}\n"
        )
    assert not old_root.exists()
    assert (
        ChrononRepository(vault="mine").read("notes.md")["content"] == "remember this"
    )
    assert ChrononRepository(vault="mine").history("notes.md") == history
    unchanged = runner.invoke(app, args)
    assert unchanged.exit_code == 0, unchanged.output
    if json_output:
        assert json.loads(unchanged.output)["updated"] is False
    else:
        assert "already points to" in unchanged.output


def test_set_vault_path_is_only_an_admin_command_and_requires_path(
    tmp_path: Path,
) -> None:
    root = tmp_path / "repo"
    init_repository(root, register_vault="mine")
    before = vaults.registry_path().read_bytes()

    assert runner.invoke(app, ["set-vault-path", "mine", str(root)]).exit_code == 2
    assert runner.invoke(app, ["admin", "set-vault-path", "mine"]).exit_code == 2
    assert vaults.registry_path().read_bytes() == before


@pytest.mark.parametrize("command", ["add-vault", "init"])
def test_cli_registration_cannot_change_an_existing_vault_path(
    tmp_path: Path, command: str
) -> None:
    old_root, new_root = tmp_path / "old", tmp_path / "new"
    init_repository(old_root, register_vault="mine")
    init_repository(new_root)
    before = vaults.registry_path().read_bytes()
    args = (
        ["add-vault", "mine", str(new_root), "--json"]
        if command == "add-vault"
        else ["init", str(new_root), "--register", "mine", "--json"]
    )

    result = runner.invoke(app, args)

    assert result.exit_code == 4, result.output
    assert json.loads(result.output)["error"] == "invalid_argument"
    assert str(old_root) not in result.output
    assert vaults.registry_path().read_bytes() == before


@pytest.mark.skipif(
    sys.platform == "win32", reason="XDG config directories are POSIX-only"
)
def test_config_home_uses_xdg_directory(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("CHRONON_CONFIG_HOME")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    assert vaults.config_home() == tmp_path / "xdg" / "chronon"


def test_config_home_uses_appdata_on_windows(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("CHRONON_CONFIG_HOME")
    monkeypatch.setattr(vaults.sys, "platform", "win32")
    monkeypatch.setenv("APPDATA", str(tmp_path / "AppData" / "Roaming"))
    assert vaults.config_home() == tmp_path / "AppData" / "Roaming" / "chronon"


def test_registry_survives_across_processes(tmp_path: Path) -> None:
    """The registry is a plain file, not process state — a second 'process'
    (here: a second call chain with a fresh Store) must see the same vaults."""
    root = tmp_path / "proj"
    init_repository(root)
    vaults.add_vault("mine", root)
    assert vaults.resolve_vault("mine") == root.resolve()
    # simulate a fresh process re-reading the registry from disk
    assert vaults.list_vaults()["mine"] == str(root.resolve())


def test_concurrent_vault_additions_do_not_lose_entries(tmp_path: Path) -> None:
    root = tmp_path / "proj"
    init_repository(root)
    context = multiprocessing.get_context("spawn")
    start = context.Event()
    results = context.Queue()
    workers = [
        context.Process(
            target=_add_vault_worker,
            args=(f"vault-{index}", str(root), start, results),
        )
        for index in range(4)
    ]
    for worker in workers:
        worker.start()
    start.set()
    for worker in workers:
        worker.join(timeout=20)
        assert worker.exitcode == 0

    outcomes = [results.get(timeout=2) for _ in workers]
    assert all(success for success, _ in outcomes), outcomes
    assert set(vaults.list_vaults()) == {f"vault-{index}" for index in range(4)}


# ── .chronon-workspace pin (core/vaults.py: set_vault/unset_vault) ─────────


def test_set_vault_requires_a_registered_vault(tmp_path: Path) -> None:
    with pytest.raises(InvalidArgument):
        vaults.set_vault("nope", tmp_path)


def test_set_vault_writes_pin_and_read_workspace_vault_finds_it(
    tmp_path: Path,
) -> None:
    root = tmp_path / "proj"
    init_repository(root)
    vaults.add_vault("mine", root)

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    added = vaults.set_vault("mine", workspace)
    assert added == {
        "path": str(workspace / vaults.WORKSPACE_FILE),
        "vault": "mine",
        "created": True,
    }

    # discovered from the pinned directory itself, and from a subdirectory
    assert vaults.read_workspace_vault(workspace) == "mine"
    nested = workspace / "sub" / "dir"
    nested.mkdir(parents=True)
    assert vaults.read_workspace_vault(nested) == "mine"

    # re-pinning updates in place rather than erroring
    again = vaults.set_vault("mine", workspace)
    assert again["created"] is False


def test_read_workspace_vault_returns_none_without_a_pin(tmp_path: Path) -> None:
    assert vaults.read_workspace_vault(tmp_path) is None


def test_unset_vault_removes_the_pin(tmp_path: Path) -> None:
    root = tmp_path / "proj"
    init_repository(root)
    vaults.add_vault("mine", root)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    vaults.set_vault("mine", workspace)

    removed = vaults.unset_vault(workspace)
    assert removed == {"path": str(workspace / vaults.WORKSPACE_FILE), "removed": True}
    assert vaults.read_workspace_vault(workspace) is None


def test_unset_vault_without_a_pin_raises(tmp_path: Path) -> None:
    with pytest.raises(InvalidArgument):
        vaults.unset_vault(tmp_path)


def test_repository_resolves_root_via_workspace_pin(
    tmp_path: Path, monkeypatch
) -> None:
    """A workspace pin lets ChrononRepository() with no --vault resolve, even
    though the workspace directory itself is not a chronon repository."""
    root = tmp_path / "proj"
    init_repository(root)
    vaults.add_vault("mine", root)
    (root / "docs.yml").write_text("value: 1\n", encoding="utf-8")

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    vaults.set_vault("mine", workspace)
    monkeypatch.chdir(workspace)

    repo = ChrononRepository()
    assert repo.root == root.resolve()


def test_an_actual_vault_directory_wins_over_a_workspace_pin(
    tmp_path: Path, monkeypatch
) -> None:
    """Being inside a real vault takes precedence over any pin above it."""
    other = tmp_path / "other"
    init_repository(other)
    vaults.add_vault("other", other)

    root = tmp_path / "proj"
    init_repository(root)
    vaults.set_vault("other", tmp_path)  # pin at an ancestor of `root`
    monkeypatch.chdir(root)

    repo = ChrononRepository()
    assert repo.root == root.resolve()


# ── CLI: `chronon set-vault` / `unset-vault` ────────────────────────────────


def test_cli_set_vault_then_bare_commands_resolve_it(
    tmp_path: Path, monkeypatch
) -> None:
    root = tmp_path / "proj"
    assert runner.invoke(app, ["init", str(root), "--register", "mine"]).exit_code == 0
    (root / "docs.yml").write_text("value: 1\n", encoding="utf-8")

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    pin = runner.invoke(app, ["set-vault", "mine", str(workspace), "--json"])
    assert pin.exit_code == 0, pin.output
    assert json.loads(pin.output)["vault"] == "mine"

    monkeypatch.chdir(workspace)
    added = runner.invoke(app, ["add", "docs.yml"])
    assert added.exit_code == 0, added.output
    result = runner.invoke(app, ["status", "docs.yml", "--json"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["state"] == "untracked"

    unpin = runner.invoke(app, ["unset-vault", "--json"])
    assert unpin.exit_code == 0, unpin.output
    assert runner.invoke(app, ["status", "docs.yml", "--json"]).exit_code != 0


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
    assert json.loads(listing.output)["vaults"] == [{"name": "mine"}]

    remove = runner.invoke(app, ["remove-vault", "mine", "--json"])
    assert remove.exit_code == 0, remove.output
    assert (
        runner.invoke(app, ["list-vaults", "--json"]).output.strip()
        == json.dumps({"vaults": []}, ensure_ascii=False, indent=2).strip()
    )


def test_vault_listing_exposes_only_sorted_names(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "private storage"
    init_repository(root, register_vault="zeta")
    vaults.add_vault("alpha", root)
    monkeypatch.chdir(tmp_path)

    expected = {"vaults": [{"name": "alpha"}, {"name": "zeta"}]}
    assert list_vaults() == expected
    plain = runner.invoke(app, ["list-vaults"])
    assert plain.exit_code == 0, plain.output
    assert plain.output == "alpha\nzeta\n"
    structured = runner.invoke(app, ["list-vaults", "--json"])
    assert structured.exit_code == 0, structured.output
    assert json.loads(structured.output) == expected


@pytest.mark.parametrize("offline", [False, True])
def test_admin_vault_path_reports_registered_path(
    tmp_path: Path, monkeypatch, offline: bool
) -> None:
    root = tmp_path / "private storage"
    init_repository(root, register_vault="mine")
    if offline:
        root.rename(tmp_path / "moved storage")
    monkeypatch.chdir(tmp_path)

    plain = runner.invoke(app, ["admin", "vault-path", "mine"])
    assert plain.exit_code == 0, plain.output
    assert plain.output == f"{root.resolve()}\n"
    structured = runner.invoke(app, ["admin", "vault-path", "mine", "--json"])
    assert structured.exit_code == 0, structured.output
    assert json.loads(structured.output) == {
        "name": "mine",
        "path": str(root.resolve()),
    }


def test_admin_vault_path_requires_a_registered_name() -> None:
    result = runner.invoke(app, ["admin", "vault-path", "missing", "--json"])
    assert result.exit_code == 4
    error = json.loads(result.output)
    assert error["error"] == "invalid_argument"
    assert error["name"] == "missing"


def test_cli_init_accepts_a_directory_matching_a_vault_name(
    tmp_path: Path, monkeypatch
) -> None:
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
    human = runner.invoke(app, ["init", str(root), "--register", "mine"])
    assert "Registered vault mine" in human.output
    result = runner.invoke(app, ["init", str(root), "--register", "mine", "--json"])
    assert result.exit_code == 0, result.output
    assert vaults.resolve_vault("mine") == root.resolve()


# ── CLI: global --vault/-v works from any cwd ──────────────────────────────


def test_cli_explicit_vault_flag_works_from_unrelated_cwd(
    tmp_path: Path, monkeypatch
) -> None:
    root = tmp_path / "proj"
    assert runner.invoke(app, ["init", str(root), "--register", "mine"]).exit_code == 0
    (root / "docs.yml").write_text("value: 1\n", encoding="utf-8")

    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)

    assert runner.invoke(app, ["--vault", "mine", "add", "docs.yml"]).exit_code == 0
    rev = json.loads(
        runner.invoke(app, ["-v", "mine", "read", "docs.yml", "--json"]).output
    )["working_revision"]
    committed = runner.invoke(
        app,
        ["--vault", "mine", "commit", "docs.yml", "-m", "initial", "--if-match", rev],
    )
    assert committed.exit_code == 0, committed.output

    status = runner.invoke(app, ["--vault", "mine", "status", "docs.yml", "--json"])
    assert json.loads(status.output)["state"] == "clean"


# ── global option discoverability and entry point ──────────────────────────


def test_cli_help_shows_vault_as_a_global_option() -> None:
    root_help = runner.invoke(app, ["--help"])
    assert root_help.exit_code == 0
    help_output = unstyle(root_help.output)
    assert "--vault" in help_output
    assert "-v" in help_output

    command_help = runner.invoke(app, ["diff", "--help"])
    assert command_help.exit_code == 0
    assert "--vault" not in command_help.output


def test_cli_main_accepts_global_vault_option(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """The real entry point accepts `chronon --vault NAME COMMAND ...`."""
    root = tmp_path / "proj"
    assert runner.invoke(app, ["init", str(root), "--register", "mine"]).exit_code == 0
    (root / "docs.yml").write_text("value: 1\n", encoding="utf-8")

    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    monkeypatch.setattr("sys.argv", ["chronon", "add", "docs.yml", "--vault", "mine"])

    with pytest.raises(SystemExit) as excinfo:
        main()
    assert excinfo.value.code in (0, None)
    assert "docs.yml" in capsys.readouterr().out


@pytest.mark.parametrize(
    "arguments",
    [
        ["status", "--vault", "mine", "docs.yml", "--json"],
        ["status", "docs.yml", "--vault", "mine", "--json"],
        ["status", "docs.yml", "--vault=mine", "--json"],
        ["status", "docs.yml", "-v", "mine", "--json"],
        ["status", "docs.yml", "-vmine", "--json"],
    ],
)
def test_cli_accepts_vault_option_after_subcommand(
    tmp_path: Path, monkeypatch, arguments: list[str]
) -> None:
    root = tmp_path / "proj"
    assert runner.invoke(app, ["init", str(root), "--register", "mine"]).exit_code == 0
    (root / "docs.yml").write_text("value: 1\n", encoding="utf-8")
    monkeypatch.chdir(root)
    assert runner.invoke(app, ["add", "docs.yml"]).exit_code == 0

    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)

    result = runner.invoke(app, arguments)
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["state"] == "untracked"


def test_cli_status_accepts_vault_after_command(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "proj"
    assert runner.invoke(app, ["init", str(root), "--register", "mine"]).exit_code == 0

    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)

    result = runner.invoke(app, ["status", "--vault", "mine", "--json"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["resources"] == []
