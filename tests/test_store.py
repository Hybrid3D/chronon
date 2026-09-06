from pathlib import Path

import pytest

from chronon.api.operations import ChrononRepository, init_repository
from chronon.core.errors import FileError, NotImplementedMode


def test_init_is_idempotent_and_writes_gitignore(tmp_path: Path) -> None:
    first = init_repository(tmp_path)
    second = init_repository(tmp_path)

    assert first["created"] is True
    assert second["created"] is False
    assert (tmp_path / ".chronon" / "config.toml").is_file()
    assert (tmp_path / ".gitignore").read_text().splitlines().count("/.chronon/") == 1


def test_auto_mode_is_explicitly_rejected(tmp_path: Path) -> None:
    with pytest.raises(NotImplementedMode) as error:
        init_repository(tmp_path, "auto")
    assert error.value.code == "not_implemented"
    assert not (tmp_path / ".chronon").exists()


def test_init_rejects_metadata_file_collision(tmp_path: Path) -> None:
    (tmp_path / ".chronon").write_text("collision", encoding="utf-8")
    with pytest.raises(FileError):
        init_repository(tmp_path)


def test_repository_is_discovered_from_nested_directory(tmp_path: Path) -> None:
    init_repository(tmp_path)
    nested = tmp_path / "a" / "b"
    nested.mkdir(parents=True)
    assert ChrononRepository(nested).root == tmp_path


def test_cannot_track_outside_or_metadata(tmp_path: Path) -> None:
    init_repository(tmp_path)
    repository = ChrononRepository(tmp_path)
    with pytest.raises(FileError):
        repository.add(tmp_path.parent / "outside.txt")
    with pytest.raises(FileError):
        repository.add(tmp_path / ".chronon" / "config.toml")


def test_add_nested_file_and_list(tmp_path: Path) -> None:
    init_repository(tmp_path)
    path = tmp_path / "nested" / "config.yml"
    path.parent.mkdir()
    path.write_text("enabled: true\n")
    repository = ChrononRepository(tmp_path)

    added = repository.add("nested/config.yml")
    again = repository.add("nested/config.yml")

    assert added["created"] is True
    assert again["created"] is False
    assert (
        repository.list_resources()["resources"][0]["resource"] == "nested/config.yml"
    )


def test_corrupt_descriptor_is_not_silently_hidden(tmp_path: Path) -> None:
    init_repository(tmp_path)
    (tmp_path / "notes.txt").write_text("notes\n", encoding="utf-8")
    repository = ChrononRepository(tmp_path)
    repository.add("notes.txt")
    repository.store.descriptor_path("notes.txt").write_text(
        "not json\n", encoding="utf-8"
    )

    with pytest.raises(FileError, match="descriptor is corrupt"):
        repository.list_resources()
