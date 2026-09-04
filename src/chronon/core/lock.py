from __future__ import annotations

import hashlib
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from filelock import FileLock

from .store import Store


@contextmanager
def exclusive_file_lock(path: Path) -> Iterator[None]:
    """Hold an inter-process lock at ``path`` on every supported platform.

    ``fcntl`` is not available on Windows.  The former thread-lock fallback only
    serialized callers inside one Python process, which let two CLI/MCP processes
    update the same history concurrently.  ``filelock`` uses the native locking
    primitive on both POSIX and Windows while keeping the lock file reusable.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with FileLock(path):
        yield


@contextmanager
def resource_operation_lock(store: Store, resource: str) -> Iterator[None]:
    """Serialize a short read-check-mutate operation for one resource."""
    digest = hashlib.sha256(resource.encode("utf-8")).hexdigest()
    directory = store.metadata / "locks"
    path = directory / f"{digest}.lock"
    with exclusive_file_lock(path):
        yield
