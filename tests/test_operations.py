import json
import multiprocessing
import os
from pathlib import Path

import pytest

from chronon.api.operations import ChrononRepository, init_repository
from chronon.core.errors import (
    FileError,
    ForeignChange,
    NothingToCommit,
    PreconditionRequired,
    RevisionConflict,
    ValidationFailed,
)


def _concurrent_commit_worker(root: str, value: int, start, result) -> None:
    """Process target kept at module scope so Windows ``spawn`` can import it."""
    start.wait()
    try:
        ChrononRepository(root).write(
            "docs.yml", f"value: {value}\n", message=f"worker {value}"
        )
    except Exception as exc:  # pragma: no cover - asserted through the queue
        result.put((False, repr(exc)))
    else:
        result.put((True, value))


@pytest.fixture
def repository(tmp_path: Path) -> ChrononRepository:
    init_repository(tmp_path)
    (tmp_path / "docs.yml").write_text(
        "servers:\n  web:\n    port: 8080\n", encoding="utf-8"
    )
    repo = ChrononRepository(tmp_path)
    repo.add("docs.yml")
    return repo


def _working_revision(repository: ChrononRepository, resource: str = "docs.yml") -> str:
    return repository.read(resource)["working_revision"]


def _commit(
    repository: ChrononRepository,
    message: str,
    author: str | None = None,
    resource: str = "docs.yml",
) -> dict:
    return repository.commit(
        resource,
        message,
        author,
        expected_revision=_working_revision(repository, resource),
    )


def test_add_commit_log_and_read(repository: ChrononRepository) -> None:
    untracked = repository.status("docs.yml")
    assert untracked["state"] == "untracked"
    assert untracked["history_count"] == 0
    assert untracked["latest_commit_at"] is None
    committed = _commit(repository, "initial", "agent-1")

    assert committed["commit"]["seq"] == 1
    status = repository.status("docs.yml")
    assert status["state"] == "clean"
    assert status["history_count"] == 1
    assert status["latest_commit_at"] == committed["commit"]["timestamp"]
    assert repository.history("docs.yml")["commits"][0]["message"] == "initial"
    assert (
        repository.read("docs.yml", "1", "parsed")["content"]["servers"]["web"]["port"]
        == 8080
    )


def test_structural_diff_and_one_shot_commit(repository: ChrononRepository) -> None:
    _commit(repository, "initial")
    result = repository.set_value(
        "docs.yml", "servers.web.port", "9090", "int", "change port"
    )

    assert result["committed"] is True
    comparison = repository.diff("docs.yml", 1, 2)
    assert comparison["changes"] == [
        {"op": "modified", "path": "servers.web.port", "old": 8080, "new": 9090}
    ]


def test_write_dirty_then_commit(repository: ChrononRepository) -> None:
    _commit(repository, "initial")
    repository.write("docs.yml", "servers:\n  web:\n    port: 8081\n")
    assert repository.status("docs.yml")["state"] == "dirty"
    _commit(repository, "increment")
    assert repository.status("docs.yml")["state"] == "clean"


def test_external_edit_is_foreign_and_can_be_accepted(
    repository: ChrononRepository,
) -> None:
    _commit(repository, "initial")
    repository.store.working_path("docs.yml").write_text(
        "servers: {}\n", encoding="utf-8"
    )
    assert repository.status("docs.yml")["state"] == "foreign"
    with pytest.raises(ForeignChange):
        repository.write("docs.yml", "servers: null\n")
    accepted = repository.accept_foreign("docs.yml")
    assert accepted["state"] == "dirty"
    _commit(repository, "accept external")


def test_status_reports_invalid_foreign_content_without_crashing(
    repository: ChrononRepository,
) -> None:
    _commit(repository, "initial")
    repository.store.working_path("docs.yml").write_text(
        "broken: [\n", encoding="utf-8"
    )
    status = repository.status("docs.yml")
    assert status["state"] == "foreign"
    assert status["diff"] is None
    assert status["validation_issues"]


def test_discard_protects_foreign_change(repository: ChrononRepository) -> None:
    _commit(repository, "initial")
    path = repository.store.working_path("docs.yml")
    path.write_text("external: true\n", encoding="utf-8")
    with pytest.raises(ForeignChange):
        repository.discard("docs.yml")
    repository.discard("docs.yml", force=True)
    assert "port: 8080" in path.read_text(encoding="utf-8")


def test_rollback_creates_new_commit(repository: ChrononRepository) -> None:
    _commit(repository, "initial")
    repository.set_value("docs.yml", "servers.web.port", "9090", "int", "change")
    rolled_back = repository.rollback("docs.yml", 1, "restore")

    assert rolled_back["commit"]["seq"] == 3
    assert (
        repository.read("docs.yml", "working", "parsed")["content"]["servers"]["web"][
            "port"
        ]
        == 8080
    )


def test_rollback_to_latest_after_dirty_work_is_rejected_without_mutation(
    repository: ChrononRepository,
) -> None:
    _commit(repository, "initial")
    dirty = "servers:\n  web:\n    port: 9090\n"
    repository.write("docs.yml", dirty)

    with pytest.raises(NothingToCommit):
        repository.rollback(
            "docs.yml",
            "latest",
            "abandon experiment",
            expected_revision=_working_revision(repository),
        )

    assert (
        repository.store.working_path("docs.yml").read_text(encoding="utf-8") == dirty
    )
    assert len(repository.history("docs.yml")["commits"]) == 1


def test_path_history_folds_unrelated_commits(repository: ChrononRepository) -> None:
    _commit(repository, "initial")
    repository.set_value("docs.yml", "other", "1", "int", "unrelated")
    repository.set_value("docs.yml", "servers.web.port", "9090", "int", "port")
    events = repository.path_history("docs.yml", "servers.web.port")["events"]

    assert [event["seq"] for event in events] == [1, 3]
    assert [event["value"] for event in events] == [8080, 9090]


def test_path_history_since_does_not_invent_change(
    repository: ChrononRepository,
) -> None:
    _commit(repository, "initial")
    repository.set_value("docs.yml", "other", "1", "int", "unrelated")
    index = repository.store.resource_dir("docs.yml") / "index.jsonl"
    entries = [
        json.loads(line) for line in index.read_text(encoding="utf-8").splitlines()
    ]
    entries[0]["timestamp"] = "2026-01-01T00:00:00Z"
    entries[1]["timestamp"] = "2026-01-02T00:00:00Z"
    index.write_text(
        "".join(json.dumps(entry) + "\n" for entry in entries), encoding="utf-8"
    )

    events = repository.path_history(
        "docs.yml", "servers.web.port", since="2026-01-01T12:00:00Z"
    )["events"]
    assert events == []


def test_invalid_yaml_never_replaces_working_copy(
    repository: ChrononRepository,
) -> None:
    original = repository.store.working_path("docs.yml").read_text(encoding="utf-8")
    with pytest.raises(ValidationFailed):
        repository.write(
            "docs.yml",
            "broken: [\n",
            expected_revision=_working_revision(repository),
        )
    assert (
        repository.store.working_path("docs.yml").read_text(encoding="utf-8")
        == original
    )


@pytest.mark.skipif(os.name == "nt", reason="POSIX permission bits are not portable")
def test_write_preserves_file_permissions(repository: ChrononRepository) -> None:
    path = repository.store.working_path("docs.yml")
    path.chmod(0o640)
    repository.write(
        "docs.yml",
        "servers: {}\n",
        expected_revision=_working_revision(repository),
    )
    assert path.stat().st_mode & 0o777 == 0o640


def test_json_schema_validation(tmp_path: Path) -> None:
    init_repository(tmp_path)
    path = tmp_path / "config.json"
    path.write_text('{"port": 8080}\n', encoding="utf-8")
    repository = ChrononRepository(tmp_path)
    repository.add("config.json")
    repository.register_schema(
        "config.json",
        {
            "type": "object",
            "properties": {"port": {"type": "integer"}},
            "required": ["port"],
        },
    )
    with pytest.raises(ValidationFailed):
        repository.write(
            "config.json",
            json.dumps({"port": "wrong"}),
            expected_revision=_working_revision(repository, "config.json"),
        )


def test_clean_commit_is_rejected(repository: ChrononRepository) -> None:
    _commit(repository, "initial")
    with pytest.raises(NothingToCommit):
        repository.commit("docs.yml", "duplicate")


def test_list_directory_shows_only_tracked_immediate_entries(tmp_path: Path) -> None:
    init_repository(tmp_path)
    (tmp_path / "root.txt").write_text("root\n", encoding="utf-8")
    (tmp_path / "ignored.txt").write_text("ignored\n", encoding="utf-8")
    (tmp_path / "nested").mkdir()
    (tmp_path / "nested" / "child.txt").write_text("child\n", encoding="utf-8")
    repository = ChrononRepository(tmp_path)
    repository.add("root.txt")
    repository.add("nested/child.txt")

    root = repository.list_directory()
    assert root["directory"] == "."
    assert root["entries"] == [
        {"name": "nested", "path": "nested", "type": "directory"},
        {"name": "root.txt", "path": "root.txt", "type": "file"},
    ]
    assert repository.list_directory("nested")["entries"] == [
        {"name": "child.txt", "path": "nested/child.txt", "type": "file"}
    ]


def test_put_creates_tracks_and_updates_resource(tmp_path: Path) -> None:
    init_repository(tmp_path)
    repository = ChrononRepository(tmp_path)

    created = repository.put("nested/notes.txt", "first\n")
    assert created["resource"] == "nested/notes.txt"
    assert created["created"] is True
    assert created["written"] is True
    assert created["tracked"] is True
    assert created["committed"] is False
    assert created["state"] == "untracked"
    assert created["working_revision"].startswith("w0:sha256:")
    assert repository.read("nested/notes.txt")["content"] == "first\n"

    updated = repository.put(
        "nested/notes.txt",
        "second\n",
        "update notes",
        expected_revision=created["working_revision"],
    )
    assert updated["created"] is False
    assert updated["committed"] is True
    assert repository.read("nested/notes.txt")["content"] == "second\n"


def test_put_refuses_to_overwrite_existing_untracked_file(tmp_path: Path) -> None:
    init_repository(tmp_path)
    path = tmp_path / "existing.txt"
    path.write_text("keep me\n", encoding="utf-8")
    repository = ChrononRepository(tmp_path)

    with pytest.raises(FileError):
        repository.put("existing.txt", "replacement\n")

    assert path.read_text(encoding="utf-8") == "keep me\n"
    assert repository.store.is_tracked("existing.txt") is False


def test_put_validation_failure_does_not_create_resource(tmp_path: Path) -> None:
    init_repository(tmp_path)
    repository = ChrononRepository(tmp_path)

    with pytest.raises(ValidationFailed):
        repository.put("nested/broken.yml", "broken: [\n")

    assert (tmp_path / "nested" / "broken.yml").exists() is False
    assert repository.store.is_tracked("nested/broken.yml") is False


def test_scratch_write_requires_observed_revision_before_overwrite(
    repository: ChrononRepository,
) -> None:
    _commit(repository, "initial")
    clean_revision = _working_revision(repository)
    scratch = repository.write(
        "docs.yml",
        "servers:\n  web:\n    port: 8081\n",
        expected_revision=clean_revision,
    )

    assert scratch["state"] == "dirty"
    assert scratch["working_revision"] != clean_revision
    with pytest.raises(PreconditionRequired):
        repository.write("docs.yml", "servers: {}\n")
    with pytest.raises(RevisionConflict):
        repository.write("docs.yml", "servers: {}\n", expected_revision=clean_revision)
    assert repository.read("docs.yml")["content"].endswith("port: 8081\n")


def test_message_write_commits_scratch_lineage(repository: ChrononRepository) -> None:
    _commit(repository, "initial")
    first = repository.write(
        "docs.yml",
        "servers:\n  web:\n    port: 8081\nscratch: true\n",
    )
    committed = repository.write(
        "docs.yml",
        "servers:\n  web:\n    port: 8082\nscratch: true\nfinal: true\n",
        "finish edit",
        expected_revision=first["working_revision"],
    )

    assert committed["committed"] is True
    assert committed["state"] == "clean"
    assert committed["working_revision"] != first["working_revision"]
    latest = repository.read("docs.yml", "latest")["content"]
    assert "scratch: true" in latest
    assert "final: true" in latest


def test_discard_requires_current_scratch_revision(
    repository: ChrononRepository,
) -> None:
    _commit(repository, "initial")
    scratch = repository.write("docs.yml", "servers: {}\n")

    with pytest.raises(PreconditionRequired):
        repository.discard("docs.yml")
    with pytest.raises(RevisionConflict):
        repository.discard("docs.yml", expected_revision="stale")
    discarded = repository.discard(
        "docs.yml", expected_revision=scratch["working_revision"]
    )
    assert discarded["state"] == "clean"


def test_force_discard_honors_a_supplied_revision(
    repository: ChrononRepository,
) -> None:
    _commit(repository, "initial")
    path = repository.store.working_path("docs.yml")
    observed = repository.status("docs.yml")["working_revision"]
    path.write_text("external: true\n", encoding="utf-8")

    with pytest.raises(RevisionConflict):
        repository.discard("docs.yml", force=True, expected_revision=observed)

    assert path.read_text(encoding="utf-8") == "external: true\n"


def test_accept_foreign_can_require_the_observed_revision(
    repository: ChrononRepository,
) -> None:
    _commit(repository, "initial")
    path = repository.store.working_path("docs.yml")
    path.write_text("external: true\n", encoding="utf-8")
    observed = repository.status("docs.yml")["working_revision"]
    path.write_text("external: changed again\n", encoding="utf-8")

    with pytest.raises(RevisionConflict):
        repository.accept_foreign("docs.yml", observed)

    current = repository.status("docs.yml")["working_revision"]
    accepted = repository.accept_foreign("docs.yml", current)
    assert accepted["state"] == "dirty"


def test_rollback_refuses_an_unobserved_foreign_change(
    repository: ChrononRepository,
) -> None:
    _commit(repository, "initial")
    repository.set_value("docs.yml", "servers.web.port", "9090", "int", "change")
    path = repository.store.working_path("docs.yml")
    path.write_text("external: true\n", encoding="utf-8")

    with pytest.raises(ForeignChange):
        repository.rollback("docs.yml", 1, "restore")

    assert path.read_text(encoding="utf-8") == "external: true\n"
    observed = repository.status("docs.yml")["working_revision"]
    restored = repository.rollback("docs.yml", 1, "restore", expected_revision=observed)
    assert restored["commit"]["seq"] == 3


def test_missing_working_copy_is_visible_and_recoverable(
    repository: ChrononRepository,
) -> None:
    _commit(repository, "initial")
    repository.store.working_path("docs.yml").unlink()

    status = repository.status("docs.yml")
    assert status["state"] == "missing"
    assert status["working_revision"] is None
    assert repository.list_resources()["resources"][0]["state"] == "missing"

    restored = repository.discard("docs.yml")
    assert restored["state"] == "clean"
    assert "port: 8080" in repository.read("docs.yml")["content"]


def test_concurrent_process_commits_keep_a_contiguous_history(tmp_path: Path) -> None:
    init_repository(tmp_path)
    (tmp_path / "docs.yml").write_text("value: 0\n", encoding="utf-8")
    repository = ChrononRepository(tmp_path)
    repository.add("docs.yml")
    _commit(repository, "initial")

    context = multiprocessing.get_context("spawn")
    start = context.Event()
    results = context.Queue()
    workers = [
        context.Process(
            target=_concurrent_commit_worker,
            args=(str(tmp_path), value, start, results),
        )
        for value in range(1, 5)
    ]
    for worker in workers:
        worker.start()
    start.set()
    for worker in workers:
        worker.join(timeout=20)
        assert worker.exitcode == 0

    outcomes = [results.get(timeout=2) for _ in workers]
    assert all(success for success, _ in outcomes), outcomes
    commits = repository.history("docs.yml")["commits"]
    assert [commit["seq"] for commit in reversed(commits)] == [1, 2, 3, 4, 5]
