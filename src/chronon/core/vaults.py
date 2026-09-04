"""Global (per-user) registry mapping vault names to chronon repository roots.

A "vault" is nothing more than a name for a directory that has been (or will be)
``chronon init``-ed. It lets a human or an agent operate on a repository from any
current working directory without ``cd``-ing into it first, similar in spirit to
how tools like Obsidian name a vault by location rather than by path.

The registry itself lives outside any single repository, at
``$CHRONON_CONFIG_HOME/vaults.toml`` (default ``~/.config/chronon/vaults.toml``),
because it has to be readable before we know which repository we are talking
about. Nothing here mutates repository state; it only resolves a name to a path.
"""

from __future__ import annotations

import json
import os
import re
import sys
import tempfile
import tomllib
from pathlib import Path
from typing import Any

from .errors import FileError, InvalidArgument
from .lock import exclusive_file_lock

_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")


def config_home() -> Path:
    override = os.environ.get("CHRONON_CONFIG_HOME")
    if override:
        return Path(override).expanduser()
    if sys.platform == "win32":
        windows_home = os.environ.get("APPDATA") or os.environ.get("LOCALAPPDATA")
        if windows_home:
            return Path(windows_home) / "chronon"
        return Path.home() / "AppData" / "Roaming" / "chronon"
    xdg_home = os.environ.get("XDG_CONFIG_HOME")
    if xdg_home:
        return Path(xdg_home).expanduser() / "chronon"
    return Path.home() / ".config" / "chronon"


def registry_path() -> Path:
    return config_home() / "vaults.toml"


def _atomic_write(path: Path, data: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def _load() -> dict[str, str]:
    path = registry_path()
    if not path.is_file():
        return {}
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise FileError("vault registry is invalid", path=str(path)) from exc
    vaults = data.get("vaults", {})
    if not isinstance(vaults, dict):
        raise FileError("vault registry is invalid", path=str(path))
    if not all(
        isinstance(name, str) and isinstance(value, str)
        for name, value in vaults.items()
    ):
        raise FileError("vault registry is invalid", path=str(path))
    return dict(vaults)


def _save(vaults: dict[str, str]) -> None:
    lines = [
        "# managed by 'chronon add-vault'/'remove-vault' — do not edit while chronon is running",
        "[vaults]",
    ]
    for name in sorted(vaults):
        lines.append(
            f"{json.dumps(name)} = {json.dumps(vaults[name], ensure_ascii=False)}"
        )
    _atomic_write(registry_path(), "\n".join(lines) + "\n")


def _validate_name(name: str) -> None:
    if not _NAME_RE.fullmatch(name):
        raise InvalidArgument(
            "vault name must start with a letter or digit and contain only "
            "letters, digits, '-', or '_'",
            name=name,
        )


def list_vaults() -> dict[str, str]:
    """Return {name: absolute_path} for every registered vault."""
    return _load()


def add_vault(name: str, path: str | Path) -> dict[str, Any]:
    _validate_name(name)
    resolved = Path(path).expanduser().resolve()
    if not (resolved / ".chronon" / "config.toml").is_file():
        raise FileError(
            "path is not a chronon repository",
            path=str(resolved),
            hint="run 'chronon init' there first, or pass the repository root",
        )
    with exclusive_file_lock(config_home() / "vaults.lock"):
        vaults = _load()
        created = name not in vaults
        vaults[name] = str(resolved)
        _save(vaults)
    return {"name": name, "path": str(resolved), "created": created}


def remove_vault(name: str) -> dict[str, Any]:
    with exclusive_file_lock(config_home() / "vaults.lock"):
        vaults = _load()
        if name not in vaults:
            raise InvalidArgument(
                "no such vault", name=name, hint="run 'chronon list-vaults'"
            )
        del vaults[name]
        _save(vaults)
    return {"name": name, "removed": True}


def resolve_vault(name: str) -> Path:
    vaults = _load()
    if name not in vaults:
        raise InvalidArgument(
            "no such vault", name=name, hint="run 'chronon list-vaults'"
        )
    path = Path(vaults[name])
    if not (path / ".chronon" / "config.toml").is_file():
        raise FileError(
            "vault is registered but no longer a chronon repository",
            name=name,
            path=str(path),
            hint=f"run 'chronon remove-vault {name}' or re-init at that path",
        )
    return path
