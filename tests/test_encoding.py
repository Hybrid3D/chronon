"""UTF-8 is the default encoding for tracked content, not a hard requirement.

Non-UTF-8 bytes must be tolerated and round-trip losslessly through add /
commit / read / diff / status. Only the JSON boundaries (MCP, ``--json``)
sanitise the surrogateescape code points that JSON cannot carry.
"""

import asyncio
import json
from pathlib import Path

from typer.testing import CliRunner

from chronon.api.operations import ChrononRepository, init_repository
from chronon.cli import app
from chronon.core.store import content_hash
from chronon.mcp_server import mcp

runner = CliRunner()

LATIN1 = b"caf\xe9 port: 8080\n"  # \xe9 is not valid UTF-8


def _tracked(tmp_path: Path, name: str, data: bytes) -> ChrononRepository:
    init_repository(tmp_path)
    (tmp_path / name).write_bytes(data)
    repo = ChrononRepository(tmp_path)
    repo.add(name)
    return repo


def _commit(repo: ChrononRepository, name: str, message: str) -> dict:
    revision = repo.read(name)["working_revision"]
    return repo.commit(name, message, expected_revision=revision)


def test_non_utf8_file_adds_commits_and_round_trips(tmp_path: Path) -> None:
    repo = _tracked(tmp_path, "note.txt", LATIN1)
    committed = _commit(repo, "note.txt", "latin-1 note")
    assert committed["commit"]["seq"] == 1

    snapshot = tmp_path / ".chronon" / "resources" / "note.txt" / "0001.txt"
    assert snapshot.read_bytes() == LATIN1

    result = repo.read("note.txt", "1")
    assert result["content"].encode("utf-8", "surrogateescape") == LATIN1
    assert result["encoding"] == "utf-8"
    assert result["lossy"] is True

    # snapshot hash check inside read_snapshot must still pass
    assert repo.diff("note.txt", 1, "working")["text"] == ""


def test_status_reports_foreign_for_non_utf8_working_copy(tmp_path: Path) -> None:
    repo = _tracked(tmp_path, "docs.yml", b"value: 1\n")
    _commit(repo, "docs.yml", "initial")

    repo.store.working_path("docs.yml").write_bytes(b"value: \xff\xfe\x00\n")
    status = repo.status("docs.yml")  # must not raise
    assert status["state"] == "foreign"
    assert isinstance(status["validation_issues"], list)


def test_non_utf8_json_reports_validation_issue_without_crashing(
    tmp_path: Path,
) -> None:
    repo = _tracked(tmp_path, "a.json", b'{"k": 1}\n')
    _commit(repo, "a.json", "initial")

    repo.store.working_path("a.json").write_bytes(b'{"k": \xff}\n')
    status = repo.status("a.json")
    assert status["state"] == "foreign"
    assert status["validation_issues"]
    assert status["diff"] is None


def test_content_hash_is_stable_across_a_write_read_cycle(tmp_path: Path) -> None:
    repo = _tracked(tmp_path, "note.txt", LATIN1)
    _commit(repo, "note.txt", "latin-1 note")
    reread = repo.read("note.txt", "1")["content"]
    assert content_hash(reread) == content_hash(LATIN1)


def test_cli_read_is_byte_exact_for_non_utf8_content(
    tmp_path: Path, monkeypatch
) -> None:
    _tracked(tmp_path, "note.txt", LATIN1)
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["read", "note.txt"])
    assert result.exit_code == 0, result.output
    assert result.stdout_bytes == LATIN1


def test_cli_read_json_is_serialisable_and_flags_lossy(
    tmp_path: Path, monkeypatch
) -> None:
    _tracked(tmp_path, "note.txt", LATIN1)
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["read", "note.txt", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["lossy"] is True
    assert "\udce9" not in payload["content"]


def test_mcp_read_non_utf8_is_json_safe_and_flagged(
    tmp_path: Path, monkeypatch
) -> None:
    _tracked(tmp_path, "note.txt", LATIN1)
    monkeypatch.chdir(tmp_path)
    _, result = asyncio.run(mcp.call_tool("read_resource", {"resource": "note.txt"}))
    assert result["lossy"] is True
    assert "\udce9" not in result["content"]
    json.dumps(result)  # must not raise on a lone surrogate


def test_cli_write_stdin_accepts_non_utf8_bytes(tmp_path: Path, monkeypatch) -> None:
    init_repository(tmp_path)
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(
        app,
        ["write", "note.txt", "--stdin", "--scratch"],
        input=LATIN1,
    )
    assert result.exit_code == 0, result.output
    assert (tmp_path / "note.txt").read_bytes() == LATIN1
