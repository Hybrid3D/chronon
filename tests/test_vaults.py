import json
import multiprocessing
from pathlib import Path

import pytest
from click import unstyle
from typer.testing import CliRunner

from chronon.api.operations import ChrononRepository, init_repository
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
    with pytest.raises(InvalidArgument):
        vaults.add_vault("looks-valid\n", root)


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
    assert (
        runner.invoke(app, ["list-vaults", "--json"]).output.strip()
        == json.dumps({"vaults": []}, ensure_ascii=False, indent=2).strip()
    )


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
