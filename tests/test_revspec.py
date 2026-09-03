from datetime import UTC, datetime

import pytest

from chronon.core.errors import InvalidRevspec, NoStateAt
from chronon.core.revspec import parse_time_filter, resolve_revision
from chronon.core.snapshot import Commit

COMMITS = [
    Commit(1, "2026-08-01T09:00:00Z", "a", "one", "sha256:a", "0001.yml"),
    Commit(2, "2026-08-05T12:00:00Z", "b", "two", "sha256:b", "0002.yml"),
    Commit(3, "2026-08-12T15:00:00Z", "a", "three", "sha256:c", "0003.yml"),
]


def test_resolves_seq_latest_and_relative_latest() -> None:
    assert resolve_revision(2, COMMITS, "x").commit.seq == 2
    assert resolve_revision("latest", COMMITS, "x").commit.seq == 3
    assert resolve_revision("latest~2", COMMITS, "x").commit.seq == 1


def test_resolves_date_as_of_utc_midnight() -> None:
    assert resolve_revision("2026-08-06", COMMITS, "x").commit.seq == 2
    with pytest.raises(NoStateAt):
        resolve_revision("2026-08-01", COMMITS, "x")


def test_resolves_relative_time() -> None:
    now = datetime(2026, 8, 13, 15, tzinfo=UTC)
    assert resolve_revision("2d ago", COMMITS, "x", now=now).commit.seq == 2


def test_rejects_non_time_history_boundaries() -> None:
    for value in ("working", "latest", "2", "latest~1"):
        with pytest.raises(InvalidRevspec):
            parse_time_filter(value)


def test_rejects_naive_timestamp() -> None:
    with pytest.raises(InvalidRevspec):
        resolve_revision("2026-08-01T12:00:00", COMMITS, "x")
