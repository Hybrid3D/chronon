from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .errors import FileError, NoStateAt, NothingToCommit
from .store import Store, atomic_write, content_hash


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
        return cls(
            seq=int(value["seq"]),
            timestamp=str(value["timestamp"]),
            author=str(value.get("author") or "unknown"),
            message=str(value["message"]),
            content_hash=str(value["content_hash"]),
            file=str(value["file"]),
        )

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
    path = store.resource_dir(resource) / commit.file
    try:
        content = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
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
