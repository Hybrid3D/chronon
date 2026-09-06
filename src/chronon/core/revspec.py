from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal

from .errors import InvalidRevspec, NoStateAt
from .snapshot import Commit, commit_by_seq

RELATIVE_RE = re.compile(r"^(\d+)([dhm])\s+ago$", re.IGNORECASE)
LATEST_RE = re.compile(r"^latest~(\d+)$")


@dataclass(frozen=True)
class ResolvedRevision:
    ref: str
    kind: Literal["working", "commit"]
    commit: Commit | None = None


def parse_timestamp(value: str, now: datetime | None = None) -> datetime:
    text = value.strip()
    relative = RELATIVE_RE.fullmatch(text)
    if relative:
        amount = int(relative.group(1))
        unit = relative.group(2).lower()
        delta = {
            "d": timedelta(days=amount),
            "h": timedelta(hours=amount),
            "m": timedelta(minutes=amount),
        }[unit]
        return (now or datetime.now(UTC)).astimezone(UTC) - delta
    try:
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
            return datetime.fromisoformat(text).replace(tzinfo=UTC)
        normalized = text[:-1] + "+00:00" if text.endswith(("Z", "z")) else text
        parsed = datetime.fromisoformat(normalized)
        if parsed.tzinfo is None:
            raise ValueError("timezone is required")
        return parsed.astimezone(UTC)
    except ValueError as exc:
        raise InvalidRevspec(
            "invalid revision specification",
            value=value,
            hint="seq | working | latest | latest~N | YYYY-MM-DD | ISO8601 | '7d ago'",
        ) from exc


def _commit_time(commit: Commit) -> datetime:
    return datetime.fromisoformat(commit.timestamp)


def resolve_revision(
    value: str | int,
    commits: list[Commit],
    resource: str,
    *,
    allow_working: bool = True,
    now: datetime | None = None,
) -> ResolvedRevision:
    ref = str(value)
    if ref == "working":
        if not allow_working:
            raise InvalidRevspec("working is not valid here", value=ref)
        return ResolvedRevision(ref, "working")
    if ref == "latest":
        if not commits:
            raise NoStateAt("resource has no commits", resource=resource, at=ref)
        return ResolvedRevision(ref, "commit", commits[-1])
    latest_match = LATEST_RE.fullmatch(ref)
    if latest_match:
        if not commits:
            raise NoStateAt("resource has no commits", resource=resource, at=ref)
        seq = len(commits) - int(latest_match.group(1))
        return ResolvedRevision(ref, "commit", commit_by_seq(commits, seq, resource))
    if isinstance(value, int) or ref.isdigit():
        return ResolvedRevision(
            ref, "commit", commit_by_seq(commits, int(ref), resource)
        )
    target = parse_timestamp(ref, now=now)
    eligible = [commit for commit in commits if _commit_time(commit) <= target]
    if not eligible:
        details = {"resource": resource, "at": ref}
        if commits:
            details["first_commit"] = commits[0].timestamp
        raise NoStateAt("no state exists at the requested time", **details)
    return ResolvedRevision(ref, "commit", eligible[-1])


def parse_time_filter(
    value: str | None, now: datetime | None = None
) -> datetime | None:
    if value is None:
        return None
    if value in {"working", "latest"} or value.isdigit() or LATEST_RE.fullmatch(value):
        raise InvalidRevspec("history boundaries must be time expressions", value=value)
    return parse_timestamp(value, now=now)
