"""Merge a Chronon allowlist into a workspace's Claude Code settings.

Without this, an agent working in a Chronon-backed workspace stops for approval
on every ``chronon`` invocation, which is noise rather than safety: the commands
below either change nothing or leave a revision that ``chronon rollback`` can
undo. Commands whose effect is *not* recoverable stay off the list on purpose,
so the prompts that remain are the ones worth reading.

Only ``.claude/settings.local.json`` is touched, and only its
``permissions.allow`` array. Everything else in the file — including any
``deny`` rule, which is never overridden — is preserved.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .errors import FileError, InvalidArgument
from .store import atomic_write_json

CLAUDE_SETTINGS = ".claude/settings.local.json"

# Read-only: no repository state changes, so approving each one buys nothing.
READ_COMMANDS = (
    "read",
    "show",
    "status",
    "list",
    "ls",
    "log",
    "diff",
    "path-history",
    "validate",
    "list-vaults",
)
# Mutating, but every one of these leaves a commit or a tracked resource behind,
# so a mistake is inspectable with `log`/`diff` and undoable with `rollback`.
WRITE_COMMANDS = (
    "add",
    "write",
    "commit",
    "set",
    "unset",
    "mv",
    "cp",
    "rollback",
    "schema-register",
)
# Never generated. `discard` destroys uncommitted work that no history can
# restore; `accept` silently adopts an edit Chronon deliberately flagged; the
# rest reshape the repository or the per-user vault registry. These are exactly
# the moments a human should be asked.
EXCLUDED_COMMANDS = ("discard", "accept", "init", "add-vault", "remove-vault")


def permission_rules(vault: str | None = None, write: bool = True) -> list[str]:
    """Claude Code Bash rules covering the safe part of the Chronon CLI.

    When ``vault`` is known, each command also gets a rule for the
    ``chronon --vault <name> <command>`` form, because the generated guidance
    puts the selector *before* the subcommand and prefix rules would otherwise
    miss every call.
    """
    commands = [*READ_COMMANDS, *WRITE_COMMANDS] if write else list(READ_COMMANDS)
    prefixes = ["chronon"]
    if vault:
        prefixes.append(f"chronon --vault {vault}")
    rules = [
        f"Bash({prefix} {command}:*)" for prefix in prefixes for command in commands
    ]
    rules.append("Bash(chronon --help:*)")
    return rules


def _load(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError) as exc:
        raise FileError("cannot read Claude settings", path=str(path)) from exc
    except json.JSONDecodeError as exc:
        raise InvalidArgument(
            "Claude settings are not valid JSON",
            path=str(path),
            hint="repair the file, then retry",
        ) from exc
    if not isinstance(loaded, dict):
        raise InvalidArgument("Claude settings must be a JSON object", path=str(path))
    return loaded


def _plan(
    root: Path, vault: str | None, write: bool
) -> tuple[Path, dict[str, Any] | None, list[str], list[str]]:
    """Return the settings path, the content to write (or None), added, skipped."""
    root = Path(root).expanduser().resolve()
    if not root.is_dir():
        raise InvalidArgument(
            "permissions destination must be an existing directory", path=str(root)
        )
    path = root / CLAUDE_SETTINGS
    settings = _load(path)

    permissions = settings.get("permissions")
    if permissions is None:
        permissions = {}
    elif not isinstance(permissions, dict):
        raise InvalidArgument(
            "Claude settings 'permissions' must be an object", path=str(path)
        )
    allow = permissions.get("allow", [])
    if not isinstance(allow, list):
        raise InvalidArgument(
            "Claude settings 'permissions.allow' must be an array", path=str(path)
        )
    deny = permissions.get("deny", [])
    denied = set(deny) if isinstance(deny, list) else set()

    existing = set(allow)
    added: list[str] = []
    skipped: list[str] = []
    for rule in permission_rules(vault, write):
        if rule in existing:
            continue
        if rule in denied:
            skipped.append(rule)
            continue
        added.append(rule)
        existing.add(rule)

    if not added:
        return path, None, [], skipped

    updated = dict(settings)
    updated_permissions = dict(permissions)
    updated_permissions["allow"] = [*allow, *added]
    updated["permissions"] = updated_permissions
    return path, updated, added, skipped


def ensure_permissions(
    root: Path, vault: str | None = None, write: bool = True
) -> dict[str, Any]:
    """Add the Chronon allowlist to a workspace's Claude Code settings."""
    path, content, added, skipped = _plan(root, vault, write)
    if content is None:
        return {
            "path": str(path),
            "created": False,
            "updated": False,
            "added": [],
            "skipped": skipped,
        }
    created = not path.exists()
    try:
        atomic_write_json(path, content)
    except OSError as exc:
        raise FileError("cannot write Claude settings", path=str(path)) from exc
    return {
        "path": str(path),
        "created": created,
        "updated": True,
        "added": added,
        "skipped": skipped,
    }


def check_permissions(
    root: Path, vault: str | None = None, write: bool = True
) -> dict[str, Any]:
    """Report whether the allowlist is complete. Writes nothing."""
    path, content, added, skipped = _plan(root, vault, write)
    if content is None:
        status = "current"
    else:
        status = "missing" if not path.exists() else "stale"
    return {
        "path": str(path),
        "status": status,
        "current": content is None,
        "missing_rules": added,
        "skipped": skipped,
    }
