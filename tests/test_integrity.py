import json
import os
from pathlib import Path

import pytest

from chronon.api.operations import ChrononRepository, init_repository
from chronon.core.errors import FileError, InvalidArgument, RepositoryNotFound


def _repository_with_commit(tmp_path: Path) -> ChrononRepository:
    init_repository(tmp_path)
    (tmp_path / "docs.yml").write_text("value: 1\n", encoding="utf-8")
    repository = ChrononRepository(tmp_path)
    repository.add("docs.yml")
    revision = repository.status("docs.yml")["working_revision"]
    repository.commit("docs.yml", "initial", expected_revision=revision)
    return repository


def test_history_index_rejects_a_snapshot_path_escape(tmp_path: Path) -> None:
    repository = _repository_with_commit(tmp_path)
    index = repository.store.resource_dir("docs.yml") / "index.jsonl"
    entry = json.loads(index.read_text(encoding="utf-8"))
    entry["file"] = "../../outside.yml"
    index.write_text(json.dumps(entry) + "\n", encoding="utf-8")

    with pytest.raises(FileError, match="history index is corrupt"):
        repository.read("docs.yml", "latest")


def test_snapshot_symlink_cannot_escape_metadata(tmp_path: Path) -> None:
    if os.name == "nt":
        pytest.skip("creating symlinks is not generally available on Windows")
    repository = _repository_with_commit(tmp_path)
    snapshot = repository.store.resource_dir("docs.yml") / "0001.yml"
    external = tmp_path / "outside.yml"
    external.write_text(snapshot.read_text(encoding="utf-8"), encoding="utf-8")
    snapshot.unlink()
    snapshot.symlink_to(external)

    with pytest.raises(FileError, match="escapes resource metadata"):
        repository.read("docs.yml", "latest")


def test_malformed_resource_state_is_a_domain_error(tmp_path: Path) -> None:
    repository = _repository_with_commit(tmp_path)
    state = repository.store.resource_dir("docs.yml") / "state.json"
    state.write_text("[]\n", encoding="utf-8")

    with pytest.raises(FileError, match="state is malformed"):
        repository.status("docs.yml")


def test_unsupported_repository_format_is_rejected(tmp_path: Path) -> None:
    init_repository(tmp_path)
    config = tmp_path / ".chronon" / "config.toml"
    config.write_text('format_version = 999\nmode = "manual"\n', encoding="utf-8")

    with pytest.raises(RepositoryNotFound, match="unsupported.*format"):
        ChrononRepository(tmp_path)


def test_externally_corrupted_schema_is_rejected(tmp_path: Path) -> None:
    repository = _repository_with_commit(tmp_path)
    repository.register_schema("docs.yml", {"type": "object"})
    repository._schema_path("docs.yml").write_text('{"type": 7}\n', encoding="utf-8")

    with pytest.raises(FileError, match="registered schema is invalid"):
        repository.validate("docs.yml")


def test_non_json_inferred_value_is_a_domain_error(tmp_path: Path) -> None:
    init_repository(tmp_path)
    (tmp_path / "docs.json").write_text('{"value": null}\n', encoding="utf-8")
    repository = ChrononRepository(tmp_path)
    repository.add("docs.json")
    before = (tmp_path / "docs.json").read_text(encoding="utf-8")
    revision = repository.status("docs.json")["working_revision"]

    with pytest.raises(InvalidArgument, match="represented in JSON"):
        repository.set_value(
            "docs.json", "value", "2026-09-04", expected_revision=revision
        )

    assert (tmp_path / "docs.json").read_text(encoding="utf-8") == before
