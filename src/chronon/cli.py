from __future__ import annotations

import json
import sys
from contextvars import ContextVar
from datetime import datetime
from pathlib import Path
from typing import Any

import typer

from chronon import __version__
from chronon.api.operations import (
    ChrononRepository,
    add_vault,
    init_repository,
    list_vaults,
    remove_vault,
    write_agent_instructions,
)
from chronon.core.errors import ChrononError, InvalidArgument

app = typer.Typer(
    no_args_is_help=True, help="Document-oriented local history indexed by time."
)

VAULT_HELP = (
    "Registered vault name (see 'chronon list-vaults'). Resolved from the "
    "global per-user registry instead of the current directory."
)

VAULT_OPTION = typer.Option(
    None,
    "--vault",
    "-v",
    help=VAULT_HELP,
)
_ACTIVE_VAULT: ContextVar[str | None] = ContextVar("chronon_active_vault", default=None)


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"chronon {__version__}")
        raise typer.Exit()


@app.callback()
def configure_cli(
    vault: str | None = VAULT_OPTION,
    version: bool = typer.Option(
        False,
        "--version",
        "-V",
        help="Print the installed version and exit.",
        is_eager=True,
        callback=_version_callback,
    ),
) -> None:
    """Configure global options for the command being run."""
    _ACTIVE_VAULT.set(vault)


def _active_vault() -> str | None:
    return _ACTIVE_VAULT.get()


def _echo_agents_md_result(value: dict[str, Any]) -> None:
    if value.get("created"):
        typer.echo(f"Created {value['path']}")
    elif value.get("updated"):
        typer.echo(f"Updated {value['path']}")
    else:
        typer.echo(f"{value['path']} is already up to date")


def _format_commit_time(value: str | None) -> str:
    """ISO 타임스탬프를 `ls -l`의 mtime 칸처럼 고정폭으로 줄인다. 커밋이 없으면 `-`."""
    if not value:
        return "-"
    try:
        return datetime.fromisoformat(value).strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return value[:16]


def _echo_path_change(value: dict[str, Any]) -> bool:
    """Print a `renamed: old -> new` line for a diff that spans a `chronon mv`."""
    change = value.get("path_change")
    if change and change.get("changed"):
        typer.echo(f"renamed: {change['from']} -> {change['to']}")
        return True
    return False


def _emit(value: Any, json_output: bool = False) -> None:
    if json_output:
        typer.echo(json.dumps(value, ensure_ascii=False, indent=2, default=str))
        return
    if isinstance(value, str):
        typer.echo(value, nl=bool(value) and not value.endswith("\n"))
        return
    if not isinstance(value, dict):
        typer.echo(value)
        return
    if {"root", "mode", "created"} <= value.keys():
        verb = "Initialized" if value["created"] else "Already initialized"
        typer.echo(f"{verb} {value['root']} ({value['mode']})")
        vault = value.get("vault")
        if vault:
            typer.echo(f"Registered vault {vault['name']} -> {vault['path']}")
    elif "commit" in value:
        commit = value["commit"]
        typer.echo(f"[{value['resource']} {commit['seq']}] {commit['message']}")
    elif "changes" in value:
        renamed = _echo_path_change(value)
        for change in value["changes"]:
            marker = {"added": "+", "removed": "-", "modified": "~"}[change["op"]]
            if change["op"] == "modified":
                detail = f"{change['old']!r} -> {change['new']!r}"
            else:
                detail = repr(change.get("new", change.get("old")))
            typer.echo(f"{marker} {change['path']}: {detail}")
        if not value["changes"] and not renamed:
            typer.echo("No changes")
        if value.get("text"):
            typer.echo(value["text"], nl=not value["text"].endswith("\n"))
    elif "text" in value:
        renamed = _echo_path_change(value)
        if value["text"]:
            typer.echo(value["text"], nl=not value["text"].endswith("\n"))
        elif not renamed:
            typer.echo("No changes")
    elif "commits" in value:
        for commit in value["commits"]:
            typer.echo(
                f"commit {commit['seq']}  {commit['timestamp']}  {commit['author']}"
            )
            typer.echo(f"    {commit['message']}")
        if not value["commits"]:
            typer.echo("No commits")
    elif "vaults" in value:
        vaults = value["vaults"]
        for entry in vaults:
            typer.echo(f"{entry['name']:<16} {entry['path']}")
        if not vaults:
            typer.echo("No registered vaults")
    elif "path" in value and "updated" in value:
        _echo_agents_md_result(value)
    elif "resources" in value:
        resources = value["resources"]
        for item in resources:
            if "state" in item:
                count = item.get("history_count", 0)
                latest = item.get("latest_commit_at") or "-"
                typer.echo(
                    f"{item['state']:<9} {item['resource']}  commits={count}  last={latest}"
                )
            else:
                typer.echo(item.get("resource", str(item)))
        if not resources:
            typer.echo("No tracked resources")
    elif "entries" in value:
        # `ls -l` 과 같은 자리(권한/링크수/오너/크기/mtime/이름) 감각으로 고정폭 배치한다:
        # state(권한 자리) · history_count(링크수 자리, 우측정렬) · 마지막 커밋 시각(mtime 자리) · 이름.
        for entry in value["entries"]:
            suffix = "/" if entry["type"] == "directory" else ""
            if "state" in entry:
                state = (
                    "scratch"
                    if entry["state"] in {"dirty", "untracked"}
                    else entry["state"]
                )
                count = entry.get("history_count", 0)
                when = _format_commit_time(entry.get("latest_commit_at"))
                typer.echo(
                    f"{state:<9} {count:>3}  {when:<16}  {entry['name']}{suffix}"
                )
            else:
                typer.echo(f"{entry['name']}{suffix}")
    elif "state" in value and "resource" in value:
        count = value.get("history_count", 0)
        latest = value.get("latest_commit_at") or "-"
        typer.echo(
            f"{value['state']:<9} {value['resource']}  commits={count}  last={latest}"
        )
        if value.get("id"):
            typer.echo(f"          id={value['id']}")
    elif value.get("moved"):
        typer.echo(
            f"Renamed {value['from']} -> {value['to']} "
            f"(id {value['id']}, {value['history_count']} commits)"
        )
    elif value.get("copied"):
        typer.echo(
            f"Copied {value['from']} -> {value['to']} "
            f"(id {value['id']}, from {value['source_id']}@{value['source_revision']})"
        )
    elif value.get("created") and value.get("written"):
        typer.echo(f"Created {value['resource']}")
    elif "resource" in value:
        typer.echo(f"Updated {value['resource']}")
    else:
        typer.echo(json.dumps(value, ensure_ascii=False, indent=2, default=str))


def _run(action: Any, json_output: bool = False) -> None:
    try:
        _emit(action(), json_output)
    except ChrononError as exc:
        if json_output:
            typer.echo(
                json.dumps(exc.as_dict(), ensure_ascii=False, indent=2), err=True
            )
        else:
            typer.echo(f"chronon: {exc.message}", err=True)
            for key, value in exc.details.items():
                typer.echo(f"  {key}: {value}", err=True)
        raise typer.Exit(exc.exit_code) from exc
    except (ValueError, TypeError, json.JSONDecodeError) as exc:
        if json_output:
            typer.echo(
                json.dumps(
                    {"error": "invalid_argument", "message": str(exc)},
                    ensure_ascii=False,
                    indent=2,
                ),
                err=True,
            )
        else:
            typer.echo(f"chronon: {exc}", err=True)
        raise typer.Exit(4) from exc
    except OSError as exc:
        if json_output:
            typer.echo(
                json.dumps(
                    {"error": "file_error", "message": str(exc)},
                    ensure_ascii=False,
                    indent=2,
                ),
                err=True,
            )
        else:
            typer.echo(f"chronon: {exc}", err=True)
        raise typer.Exit(3) from exc


@app.command("init")
def init_command(
    directory: Path = typer.Argument(Path("."), help="Directory to initialize."),
    mode: str = typer.Option(
        "manual", "--mode", help="Commit mode (manual; auto is planned)."
    ),
    register: str | None = typer.Option(
        None,
        "--register",
        help="Also register this directory as a named vault (see 'chronon add-vault').",
    ),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    _run(
        lambda: init_repository(directory, mode, register),
        json_output,
    )


@app.command("add-vault")
def add_vault_command(
    name: str = typer.Argument(..., help="Name to register the vault under."),
    directory: Path = typer.Argument(
        Path("."), help="Chronon repository root (already 'chronon init'-ed)."
    ),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    _run(lambda: add_vault(name, directory), json_output)


@app.command("list-vaults")
def list_vaults_command(json_output: bool = typer.Option(False, "--json")) -> None:
    _run(lambda: list_vaults(), json_output)


@app.command("remove-vault")
def remove_vault_command(
    name: str, json_output: bool = typer.Option(False, "--json")
) -> None:
    _run(lambda: remove_vault(name), json_output)


@app.command()
def add(
    resources: list[Path] = typer.Argument(..., help="Files to begin tracking."),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    _run(
        lambda: {
            "resources": [
                ChrononRepository(vault=_active_vault()).add(resource)
                for resource in resources
            ]
        },
        json_output,
    )


@app.command()
def commit(
    resource: Path,
    message: str = typer.Option(..., "--message", "-m"),
    author: str | None = typer.Option(None, "--author"),
    expected_revision: str | None = typer.Option(None, "--if-match"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    _run(
        lambda: ChrononRepository(vault=_active_vault()).commit(
            resource, message, author, expected_revision
        ),
        json_output,
    )


@app.command("mv")
def move_command(
    source: Path,
    destination: Path,
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Rename a tracked file, keeping its full history and id."""
    _run(
        lambda: ChrononRepository(vault=_active_vault()).move(source, destination),
        json_output,
    )


app.command("move", hidden=True)(move_command)


@app.command("cp")
def copy_command(
    source: Path,
    destination: Path,
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Copy a tracked file to a new path as a fresh resource.

    The copy gets a new id and its history starts at revision 0; its descriptor
    records the source id and the source revision it was copied from.
    """
    _run(
        lambda: ChrononRepository(vault=_active_vault()).copy(source, destination),
        json_output,
    )


app.command("copy", hidden=True)(copy_command)


@app.command("diff")
def diff_command(
    resource: Path,
    from_ref: str = typer.Option("latest", "--from"),
    to_ref: str = typer.Option("working", "--to"),
    format: str = typer.Option("auto", "--format"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    _run(
        lambda: ChrononRepository(vault=_active_vault()).diff(
            resource, from_ref, to_ref, format
        ),
        json_output,
    )


def _history(
    resource: Path,
    limit: int | None,
    since: str | None,
    until: str | None,
    author: str | None,
    vault: str | None,
    json_output: bool,
) -> None:
    _run(
        lambda: ChrononRepository(vault=vault).history(
            resource, limit, since, until, author
        ),
        json_output,
    )


@app.command("log")
def log_command(
    resource: Path,
    limit: int | None = typer.Option(None, "--limit", "-n"),
    since: str | None = typer.Option(None, "--since"),
    until: str | None = typer.Option(None, "--until"),
    author: str | None = typer.Option(None, "--author"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    _history(resource, limit, since, until, author, _active_vault(), json_output)


@app.command("history", hidden=True)
def history_command(
    resource: Path,
    limit: int | None = typer.Option(None, "--limit", "-n"),
    since: str | None = typer.Option(None, "--since"),
    until: str | None = typer.Option(None, "--until"),
    author: str | None = typer.Option(None, "--author"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    _history(resource, limit, since, until, author, _active_vault(), json_output)


@app.command()
def status(
    resource: Path | None = typer.Argument(None),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    _run(
        lambda: (
            ChrononRepository(vault=_active_vault()).status(resource)
            if resource
            else ChrononRepository(vault=_active_vault()).list_resources()
        ),
        json_output,
    )


@app.command("list")
def list_command(
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    _run(lambda: ChrononRepository(vault=_active_vault()).list_resources(), json_output)


@app.command("read")
def read_command(
    resource: Path,
    at: str = typer.Option("working", "--at"),
    parsed: bool = typer.Option(False, "--parsed"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    def action() -> Any:
        result = ChrononRepository(vault=_active_vault()).read(
            resource, at, "parsed" if parsed else "raw"
        )
        if not parsed and not json_output:
            return result["content"]
        return result

    _run(action, json_output)


def _list_directory(
    directory: Path,
    long_output: bool,
    json_output: bool,
) -> None:
    _run(
        lambda: ChrononRepository(vault=_active_vault()).list_directory(
            directory, long_output
        ),
        json_output,
    )


LONG_OUTPUT_OPTION = typer.Option(
    False,
    "--long",
    "-l",
    help=(
        "Add columns: state, revision count, last commit time, name "
        "(like `ls -l`'s mode/nlink/mtime, but self-describing here in --help)."
    ),
)


@app.command("ls")
def ls_command(
    directory: Path = typer.Argument(Path("."), help="Directory to list."),
    long_output: bool = LONG_OUTPUT_OPTION,
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """List immediate entries that contain Chronon-managed files."""
    _list_directory(directory, long_output, json_output)


@app.command("show")
def show_command(
    resource: Path,
    revision: str,
    parsed: bool = typer.Option(False, "--parsed"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    def action() -> Any:
        result = ChrononRepository(vault=_active_vault()).read(
            resource, revision, "parsed" if parsed else "raw"
        )
        if not parsed and not json_output:
            return result["content"]
        return result

    _run(action, json_output)


@app.command()
def write(
    resource: Path,
    content: str | None = typer.Option(None, "--content"),
    file: Path | None = typer.Option(None, "--file"),
    stdin: bool = typer.Option(False, "--stdin"),
    scratch: bool = typer.Option(
        False, "--scratch", help="Save without creating a commit."
    ),
    message: str | None = typer.Option(None, "--message", "-m"),
    author: str | None = typer.Option(None, "--author"),
    expected_revision: str | None = typer.Option(None, "--if-match"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    def action() -> dict[str, Any]:
        sources = sum(
            item is not None and item is not False for item in (content, file, stdin)
        )
        if sources != 1:
            raise InvalidArgument("choose exactly one of --content, --file, or --stdin")
        modes = int(scratch) + int(message is not None)
        if modes != 1:
            raise InvalidArgument("choose exactly one of --scratch or --message")
        if file is not None:
            value = file.read_text(encoding="utf-8")
        elif stdin:
            value = sys.stdin.read()
        else:
            value = content or ""
        return ChrononRepository(vault=_active_vault()).put(
            resource, value, message, author, expected_revision
        )

    _run(action, json_output)


@app.command("set")
def set_command(
    resource: Path,
    path: str = typer.Option(..., "--path"),
    value: str = typer.Option(..., "--value"),
    type_name: str | None = typer.Option(None, "--type"),
    message: str | None = typer.Option(None, "--message", "-m"),
    author: str | None = typer.Option(None, "--author"),
    expected_revision: str | None = typer.Option(None, "--if-match"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    _run(
        lambda: ChrononRepository(vault=_active_vault()).set_value(
            resource, path, value, type_name, message, author, expected_revision
        ),
        json_output,
    )


@app.command("unset")
def unset_command(
    resource: Path,
    path: str = typer.Option(..., "--path"),
    message: str | None = typer.Option(None, "--message", "-m"),
    author: str | None = typer.Option(None, "--author"),
    expected_revision: str | None = typer.Option(None, "--if-match"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    _run(
        lambda: ChrononRepository(vault=_active_vault()).unset_value(
            resource, path, message, author, expected_revision
        ),
        json_output,
    )


@app.command("path-history")
def path_history_command(
    resource: Path,
    path: str,
    since: str | None = typer.Option(None, "--since"),
    until: str | None = typer.Option(None, "--until"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    _run(
        lambda: ChrononRepository(vault=_active_vault()).path_history(
            resource, path, since, until
        ),
        json_output,
    )


@app.command()
def rollback(
    resource: Path,
    revision: str,
    message: str = typer.Option(..., "--message", "-m"),
    author: str | None = typer.Option(None, "--author"),
    expected_revision: str | None = typer.Option(None, "--if-match"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    _run(
        lambda: ChrononRepository(vault=_active_vault()).rollback(
            resource, revision, message, author, expected_revision
        ),
        json_output,
    )


@app.command()
def discard(
    resource: Path,
    force: bool = typer.Option(False, "--force"),
    expected_revision: str | None = typer.Option(None, "--if-match"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    _run(
        lambda: ChrononRepository(vault=_active_vault()).discard(
            resource, force, expected_revision
        ),
        json_output,
    )


@app.command("accept")
def accept_command(
    resource: Path,
    expected_revision: str | None = typer.Option(None, "--if-match"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    _run(
        lambda: ChrononRepository(vault=_active_vault()).accept_foreign(
            resource, expected_revision
        ),
        json_output,
    )


@app.command()
def validate(
    resource: Path,
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    _run(
        lambda: ChrononRepository(vault=_active_vault()).validate(resource),
        json_output,
    )


@app.command("schema-register")
def schema_register(
    resource: Path,
    file: Path = typer.Option(..., "--file"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    _run(
        lambda: ChrononRepository(vault=_active_vault()).register_schema(
            resource, json.loads(file.read_text(encoding="utf-8"))
        ),
        json_output,
    )


@app.command("agents-md")
def agents_md_command(
    directory: Path = typer.Argument(
        Path("."),
        metavar="[PATH]",
        help="Directory in which to create or refresh CHRONON.md.",
    ),
    vault: str | None = typer.Option(
        None,
        "--vault",
        "-v",
        help="Customize the guidance for this registered vault.",
    ),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Write or refresh external AI guidance for using Chronon.

    The destination defaults to the current directory and does not need to be
    inside a vault. With --vault, every example is specialized for that named
    vault. Safe to re-run: only the marked Chronon section is updated.
    """

    selected_vault = vault or _active_vault()

    def generate() -> dict[str, Any]:
        return write_agent_instructions(directory, vault=selected_vault)

    _run(
        generate,
        json_output,
    )


def main() -> None:
    app(prog_name="chronon")


if __name__ == "__main__":
    main()
