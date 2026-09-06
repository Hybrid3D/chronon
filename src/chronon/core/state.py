from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from .errors import FileError
from .snapshot import read_index
from .store import Store, atomic_write_json, content_hash
from .text import read_working_text


def read_state_file(store: Store, resource: str) -> dict[str, Any] | None:
    path = store.resource_dir(resource) / "state.json"
    if not path.exists():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise FileError("cannot read resource state", resource=resource) from exc
    if not isinstance(value, dict):
        raise FileError("resource state is malformed", resource=resource)
    return value


def update_state(
    store: Store, resource: str, content: str, last_seq: int
) -> dict[str, Any]:
    now = datetime.now(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")
    previous = read_state_file(store, resource) or {}
    previous_generation = previous.get("working_generation", 0)
    if (
        not isinstance(previous_generation, int)
        or isinstance(previous_generation, bool)
        or previous_generation < 0
    ):
        raise FileError("resource state is malformed", resource=resource)
    generation = previous_generation + 1
    value = {
        "last_written_hash": content_hash(content),
        "last_written_at": now,
        "last_seq": last_seq,
        "working_generation": generation,
    }
    atomic_write_json(
        store.resource_dir(resource) / "state.json",
        value,
    )
    return value


def working_revision(generation: int, working_hash: str) -> str:
    """Build an opaque compare-and-swap token for a working copy."""
    return f"w{generation}:{working_hash}"


def resource_state(store: Store, resource: str) -> dict[str, Any]:
    resource = store.require_tracked(resource)
    resource_id = store.ensure_resource_id(resource)
    working = store.working_path(resource)
    commits = read_index(store, resource)
    state_file = read_state_file(store, resource)
    generation = (state_file or {}).get("working_generation", 0)
    if (
        not isinstance(generation, int)
        or isinstance(generation, bool)
        or generation < 0
    ):
        raise FileError("resource state is malformed", resource=resource)
    latest_hash = commits[-1].content_hash if commits else None
    if not working.is_file():
        return {
            "resource": resource,
            "id": resource_id,
            "state": "missing",
            "working_hash": None,
            "working_generation": generation,
            "working_revision": None,
            "latest_hash": latest_hash,
            "latest_seq": commits[-1].seq if commits else None,
            "history_count": len(commits),
            "latest_commit_at": commits[-1].timestamp if commits else None,
            "mtime": None,
        }
    try:
        content = read_working_text(working)
    except OSError as exc:
        raise FileError("working copy is not readable", resource=resource) from exc
    working_hash = content_hash(content)
    if not commits:
        state = "untracked"
    elif working_hash == latest_hash:
        state = "clean"
    elif state_file and working_hash == state_file.get("last_written_hash"):
        state = "dirty"
    else:
        state = "foreign"
    return {
        "resource": resource,
        "id": resource_id,
        "state": state,
        "working_hash": working_hash,
        "working_generation": generation,
        "working_revision": working_revision(generation, working_hash),
        "latest_hash": latest_hash,
        "latest_seq": commits[-1].seq if commits else None,
        "history_count": len(commits),
        "latest_commit_at": commits[-1].timestamp if commits else None,
        "mtime": working.stat().st_mtime,
    }
