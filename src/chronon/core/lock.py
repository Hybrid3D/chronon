from __future__ import annotations

import hashlib
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from .store import Store

try:
    import fcntl
except ImportError:  # pragma: no cover - Windows fallback
    fcntl = None  # type: ignore[assignment]


_fallback_locks: dict[Path, threading.Lock] = {}
_fallback_guard = threading.Lock()


@contextmanager
def resource_operation_lock(store: Store, resource: str) -> Iterator[None]:
    """Serialize a short read-check-mutate operation for one resource."""
    digest = hashlib.sha256(resource.encode("utf-8")).hexdigest()
    directory = store.metadata / "locks"
    directory.mkdir(exist_ok=True)
    path = directory / f"{digest}.lock"

    if fcntl is not None:
        with path.open("a+b") as stream:
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
        return

    with _fallback_guard:
        lock = _fallback_locks.setdefault(path, threading.Lock())
    with lock:
        yield
