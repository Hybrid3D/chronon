import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from chronon.api.operations import ChrononRepository, init_repository
from chronon.cli import app
from chronon.core.errors import (
    FileError,
    InvalidArgument,
    ResourceAlreadyTracked,
    ResourceNotTracked,
)

runner = CliRunner()


@pytest.fixture
def repository(tmp_path: Path) -> ChrononRepository:
    init_repository(tmp_path)
    (tmp_path / "docs.yml").write_text(
        "servers:\n  web:\n    port: 8080\n", encoding="utf-8"
    )
    repo = ChrononRepository(tmp_path)
    repo.add("docs.yml")
    return repo


def _commit(repo: ChrononRepository, message: str, resource: str = "docs.yml") -> None:
    revision = repo.read(resource)["working_revision"]
    repo.commit(resource, message, expected_revision=revision)


def test_add_assigns_a_stable_id(repository: ChrononRepository) -> None:
    first = repository.status("docs.yml")["id"]
    second = repository.status("docs.yml")["id"]
    assert first == second
    assert len(first) == 32
    descriptor = json.loads(
        (repository.root / ".chronon/resources/docs.yml/resource.json").read_text()
    )
    assert descriptor["id"] == first


def test_legacy_descriptor_without_id_is_backfilled(
    repository: ChrononRepository,
) -> None:
    descriptor_path = repository.root / ".chronon/resources/docs.yml/resource.json"
    descriptor_path.write_text(json.dumps({"resource": "docs.yml"}), encoding="utf-8")

    fresh = ChrononRepository(repository.root)
    resource_id = fresh.status("docs.yml")["id"]

    assert resource_id
    assert json.loads(descriptor_path.read_text())["id"] == resource_id


def test_move_preserves_history_and_id(repository: ChrononRepository) -> None:
    _commit(repository, "initial")
    repository.set_value("docs.yml", "servers.web.port", "9090", "int", "bump")
    original_id = repository.status("docs.yml")["id"]

    result = repository.move("docs.yml", "config/web.yml")

    assert result["moved"] is True
    assert result["id"] == original_id
    assert result["from"] == "docs.yml"
    assert result["to"] == "config/web.yml"
    assert result["history_count"] == 2
    assert not (repository.root / "docs.yml").exists()
    assert (repository.root / "config/web.yml").read_text().strip().endswith("9090")
    with pytest.raises(ResourceNotTracked):
        repository.status("docs.yml")

    moved = repository.status("config/web.yml")
    assert moved["id"] == original_id
    assert moved["history_count"] == 2
    assert [c["message"] for c in repository.history("config/web.yml")["commits"]] == [
        "bump",
        "initial",
    ]
    descriptor = json.loads(
        (
            repository.root / ".chronon/resources/config/web.yml/resource.json"
        ).read_text()
    )
    paths = [entry["path"] for entry in descriptor["path_log"]]
    assert paths == ["docs.yml", "config/web.yml"]
    assert "previous_paths" not in descriptor


def test_move_can_continue_committing(repository: ChrononRepository) -> None:
    _commit(repository, "initial")
    repository.move("docs.yml", "renamed.yml")
    result = repository.set_value(
        "renamed.yml", "servers.web.port", "9091", "int", "after rename"
    )
    assert result["commit"]["seq"] == 2


def test_move_refuses_existing_destination(repository: ChrononRepository) -> None:
    _commit(repository, "initial")
    (repository.root / "taken.yml").write_text("x\n", encoding="utf-8")
    with pytest.raises(FileError):
        repository.move("docs.yml", "taken.yml")
    # source untouched
    assert (repository.root / "docs.yml").exists()
    assert repository.status("docs.yml")["state"] == "clean"


def test_move_refuses_tracked_destination(repository: ChrononRepository) -> None:
    _commit(repository, "initial")
    (repository.root / "other.yml").write_text("a: 1\n", encoding="utf-8")
    repository.add("other.yml")
    with pytest.raises(ResourceAlreadyTracked):
        repository.move("docs.yml", "other.yml")


def test_move_same_path_is_rejected(repository: ChrononRepository) -> None:
    _commit(repository, "initial")
    with pytest.raises(InvalidArgument):
        repository.move("docs.yml", "docs.yml")


def test_copy_starts_at_revision_zero_and_records_lineage(
    repository: ChrononRepository,
) -> None:
    _commit(repository, "initial")
    repository.set_value("docs.yml", "servers.web.port", "9090", "int", "bump")
    source = repository.status("docs.yml")
    source_id = source["id"]

    result = repository.copy("docs.yml", "docs-copy.yml")

    assert result["copied"] is True
    assert result["history_count"] == 0
    assert result["source_id"] == source_id
    assert result["source_revision"] == source["working_revision"]
    assert result["id"] != source_id

    # the copy is a brand-new resource: no commits, working content carried over
    copy_status = repository.status("docs-copy.yml")
    assert copy_status["id"] == result["id"]
    assert copy_status["state"] == "untracked"
    assert copy_status["history_count"] == 0
    assert repository.history("docs-copy.yml")["commits"] == []
    assert (repository.root / "docs-copy.yml").read_text() == (
        repository.root / "docs.yml"
    ).read_text()

    descriptor = json.loads(
        (repository.root / ".chronon/resources/docs-copy.yml/resource.json").read_text()
    )
    lineage = descriptor["copied_from"]
    assert lineage["id"] == source_id
    assert lineage["path"] == "docs.yml"
    assert lineage["revision"] == source["working_revision"]
    assert lineage["seq"] == source["latest_seq"]
    assert lineage["content_hash"] == source["working_hash"]

    # committing the copy begins its own timeline at seq 1
    revision = repository.read("docs-copy.yml")["working_revision"]
    repository.write(
        "docs-copy.yml",
        "servers:\n  web:\n    port: 1\n",
        "copy diverges",
        expected_revision=revision,
    )
    assert repository.history("docs-copy.yml")["commits"][0]["seq"] == 1
    # source is untouched
    assert "9090" in (repository.root / "docs.yml").read_text()


def test_copy_of_committed_state_reports_clean_lineage(
    repository: ChrononRepository,
) -> None:
    _commit(repository, "initial")
    result = repository.copy("docs.yml", "docs-copy.yml")
    descriptor = json.loads(
        (repository.root / ".chronon/resources/docs-copy.yml/resource.json").read_text()
    )
    assert descriptor["copied_from"]["state"] == "clean"
    assert descriptor["copied_from"]["seq"] == 1
    assert result["history_count"] == 0


def test_copy_refuses_existing_destination(repository: ChrononRepository) -> None:
    _commit(repository, "initial")
    (repository.root / "taken.yml").write_text("x\n", encoding="utf-8")
    with pytest.raises(FileError):
        repository.copy("docs.yml", "taken.yml")


def test_move_and_copy_carry_the_schema(repository: ChrononRepository) -> None:
    _commit(repository, "initial")
    repository.register_schema(
        "docs.yml",
        {"type": "object", "properties": {"servers": {"type": "object"}}},
    )

    repository.move("docs.yml", "moved.yml")
    assert (repository.root / ".chronon/schemas/moved.yml.schema.json").is_file()
    assert not (repository.root / ".chronon/schemas/docs.yml.schema.json").is_file()

    repository.copy("moved.yml", "copied.yml")
    assert (repository.root / ".chronon/schemas/copied.yml.schema.json").is_file()
    assert (repository.root / ".chronon/schemas/moved.yml.schema.json").is_file()


# ── CLI ──────────────────────────────────────────────────────────────────


def test_cli_mv_and_cp(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    assert runner.invoke(app, ["init", "."]).exit_code == 0
    (tmp_path / "a.yml").write_text("k: 1\n", encoding="utf-8")
    assert runner.invoke(app, ["add", "a.yml"]).exit_code == 0
    revision = json.loads(runner.invoke(app, ["read", "a.yml", "--json"]).output)[
        "working_revision"
    ]
    assert (
        runner.invoke(
            app, ["commit", "a.yml", "-m", "init", "--if-match", revision]
        ).exit_code
        == 0
    )

    moved = runner.invoke(app, ["mv", "a.yml", "b.yml"])
    assert moved.exit_code == 0, moved.output
    assert "Renamed a.yml -> b.yml" in moved.output
    assert not (tmp_path / "a.yml").exists()
    assert (tmp_path / "b.yml").exists()

    # the rename shows up in diff across the point in time it happened
    diff = runner.invoke(app, ["diff", "b.yml", "--from", "1", "--to", "working"])
    assert diff.exit_code == 0, diff.output
    assert "renamed: a.yml -> b.yml" in diff.output

    copied = runner.invoke(app, ["cp", "b.yml", "c.yml"])
    assert copied.exit_code == 0, copied.output
    assert "Copied b.yml -> c.yml" in copied.output
    assert (tmp_path / "c.yml").exists()

    log = runner.invoke(app, ["log", "c.yml"])
    assert "No commits" in log.output


def test_diff_reports_rename_between_revisions(
    repository: ChrononRepository,
) -> None:
    _commit(repository, "one")
    repository.set_value("docs.yml", "servers.web.port", "9090", "int", "two")
    repository.move("docs.yml", "sub/renamed.yml")
    repository.set_value("sub/renamed.yml", "servers.web.port", "9091", "int", "three")
    repository.set_value("sub/renamed.yml", "servers.web.port", "9092", "int", "four")

    # seq1/seq2 predate the move, seq3/seq4 postdate it
    spanning = repository.diff("sub/renamed.yml", "latest~3", "latest")
    assert spanning["path_change"] == {
        "from": "docs.yml",
        "to": "sub/renamed.yml",
        "changed": True,
    }

    within = repository.diff("sub/renamed.yml", "latest~1", "latest")
    assert within["path_change"]["changed"] is False
    assert within["path_change"]["to"] == "sub/renamed.yml"

    # default diff (latest..working) after a mv with no follow-up commit
    repository.move("sub/renamed.yml", "final.yml")
    pending = repository.diff("final.yml")
    assert pending["path_change"] == {
        "from": "sub/renamed.yml",
        "to": "final.yml",
        "changed": True,
    }
