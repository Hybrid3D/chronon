from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .errors import FileError, NoStateAt, NothingToCommit
from .store import Store, atomic_write, content_hash
from .text import read_working_text


def utc_now() -> datetime:
    return datetime.now(UTC)


def iso_z(value: datetime) -> str:
    return (
        value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")
    )


@dataclass(frozen=True)
class Commit:
    seq: int
    timestamp: str
    author: str
    message: str
    content_hash: str
    file: str

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> Commit:
        seq = value["seq"]
        timestamp = value["timestamp"]
        author = value.get("author") or "unknown"
        message = value["message"]
        digest = value["content_hash"]
        filename = value["file"]
        if not isinstance(seq, int) or isinstance(seq, bool) or seq < 1:
            raise ValueError("invalid commit sequence")
        if not all(
            isinstance(item, str)
            for item in (timestamp, author, message, digest, filename)
        ):
            raise ValueError("invalid commit field type")
        parsed_time = datetime.fromisoformat(timestamp)
        if parsed_time.tzinfo is None:
            raise ValueError("commit timestamp must include a timezone")
        if not re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
            raise ValueError("invalid content hash")
        if (
            not filename
            or filename in {".", ".."}
            or "/" in filename
            or "\\" in filename
        ):
            raise ValueError("invalid snapshot filename")
        return cls(seq, timestamp, author, message, digest, filename)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def read_index(store: Store, resource: str) -> list[Commit]:
    index = store.resource_dir(resource) / "index.jsonl"
    if not index.exists():
        return []
    commits: list[Commit] = []
    try:
        lines = index.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise FileError("cannot read history index", resource=resource) from exc
    for line_number, line in enumerate(lines, 1):
        if not line.strip():
            continue
        try:
            commit = Commit.from_dict(json.loads(line))
        except (ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
            raise FileError(
                "history index is corrupt",
                resource=resource,
                line=line_number,
            ) from exc
        if commit.seq != len(commits) + 1:
            raise FileError(
                "history sequence is not contiguous",
                resource=resource,
                line=line_number,
            )
        commits.append(commit)
    return commits


def snapshot_extension(resource: str) -> str:
    suffix = Path(resource).suffix
    return suffix if suffix else ".txt"


def create_snapshot(
    store: Store,
    resource: str,
    content: str,
    message: str,
    author: str,
    now: datetime | None = None,
) -> Commit:
    if not message.strip():
        raise FileError("commit message must not be empty", resource=resource)
    commits = read_index(store, resource)
    new_hash = content_hash(content)
    if commits and commits[-1].content_hash == new_hash:
        raise NothingToCommit(
            "content is identical to the latest commit",
            resource=resource,
            latest_seq=commits[-1].seq,
        )
    seq = len(commits) + 1
    filename = f"{seq:04d}{snapshot_extension(resource)}"
    timestamp = iso_z(now or utc_now())
    commit = Commit(seq, timestamp, author, message.strip(), new_hash, filename)
    snapshot = store.resource_dir(resource) / filename
    if snapshot.exists():
        raise FileError("snapshot already exists", resource=resource, seq=seq)
    atomic_write(snapshot, content)
    index = store.resource_dir(resource) / "index.jsonl"
    line = (
        json.dumps(commit.as_dict(), ensure_ascii=False, separators=(",", ":")) + "\n"
    )
    try:
        with index.open("a", encoding="utf-8", newline="") as stream:
            stream.write(line)
            stream.flush()
            os.fsync(stream.fileno())
    except OSError as exc:
        snapshot.unlink(missing_ok=True)
        raise FileError("cannot append history index", resource=resource) from exc
    return commit


def read_snapshot(store: Store, resource: str, commit: Commit) -> str:
    resource_directory = store.resource_dir(resource).resolve()
    path = resource_directory / commit.file
    try:
        resolved_path = path.resolve()
        resolved_path.relative_to(resource_directory)
    except (OSError, ValueError) as exc:
        raise FileError(
            "snapshot path escapes resource metadata",
            resource=resource,
            seq=commit.seq,
        ) from exc
    try:
        content = read_working_text(resolved_path)
    except OSError as exc:
        raise FileError(
            "cannot read snapshot", resource=resource, seq=commit.seq
        ) from exc
    if content_hash(content) != commit.content_hash:
        raise FileError(
            "snapshot content hash mismatch", resource=resource, seq=commit.seq
        )
    return content


def commit_by_seq(commits: list[Commit], seq: int, resource: str) -> Commit:
    if seq < 1 or seq > len(commits):
        raise NoStateAt("no state exists at revision", resource=resource, at=seq)
    return commits[seq - 1]
