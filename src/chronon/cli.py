from __future__ import annotations

import json
import sys
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
)
from chronon.core.errors import ChrononError

app = typer.Typer(
    no_args_is_help=True, help="Document-oriented local history indexed by time."
)
ls_app = typer.Typer(
    add_completion=False,
    help="List files managed by Chronon.",
)
cat_app = typer.Typer(
    add_completion=False,
    help="Read a file managed by Chronon.",
)
write_app = typer.Typer(
    add_completion=False,
    help="Create or update a file through Chronon.",
)
commit_app = typer.Typer(
    add_completion=False,
    help="Commit a Chronon scratch working copy.",
)

VAULT_OPTION = typer.Option(
    None,
    "--vault",
    help=(
        "Registered vault name (see 'chronon list-vaults'). Resolved from the "
        "global per-user registry, not the current directory. Omit to use the "
        "current directory instead, as before."
    ),
)


def _known_vault_names() -> set[str]:
    try:
        return {entry["name"] for entry in list_vaults()["vaults"]}
    except ChrononError:
        return set()


def _command_accepts_vault(command_name: str) -> bool:
    """True if the given top-level subcommand declares --vault (VAULT_OPTION).

    Not every command does — `init`, `add-vault`, `list-vaults`, `remove-vault`
    manage repositories/registry entries themselves rather than operating
    inside one, so they must never have their own positional arguments
    mistaken for the `[vault]` shorthand. Checking Click's parsed params
    directly (instead of hand-maintaining a name denylist) means a command
    that doesn't take --vault can never be spliced into, by construction.
    """
    from typer.main import get_command

    group = get_command(app)
    command = group.commands.get(command_name)  # type: ignore[attr-defined]
    if command is None:
        return False
    return any(param.name == "vault" for param in command.params)


def _splice_positional_vault(argv: list[str], slot: int) -> list[str]:
    """Let a bare registered vault name sit positionally at `slot`, e.g.

        chronon diff myvault docs.yml --from ...   # command, then vault, then path
        chronon-ls myvault sub/dir                  # no command: vault comes first

    Click cannot leave an optional positional argument unfilled when a later
    required one follows, so this rewrites the token into `--vault <name>`
    before Click ever parses argv. Every command that accepts a vault already
    declares --vault (VAULT_OPTION), so this is purely a convenience for the
    common case; typing `--vault myvault` explicitly always works too, in any
    position. Callers are expected to have already excluded commands that
    don't take --vault (see `_command_accepts_vault`).
    """
    if len(argv) <= slot:
        return argv
    candidate = argv[slot]
    if candidate.startswith("-"):
        return argv
    if candidate not in _known_vault_names():
        return argv
    rest = argv[:slot] + argv[slot + 1 :]
    return [*rest, "--vault", candidate]


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
        agents_md = value.get("agents_md")
        if agents_md:
            _echo_agents_md_result(agents_md)
    elif "commit" in value:
        commit = value["commit"]
        typer.echo(f"[{value['resource']} {commit['seq']}] {commit['message']}")
    elif "changes" in value:
        for change in value["changes"]:
            marker = {"added": "+", "removed": "-", "modified": "~"}[change["op"]]
            if change["op"] == "modified":
                detail = f"{change['old']!r} -> {change['new']!r}"
            else:
                detail = repr(change.get("new", change.get("old")))
            typer.echo(f"{marker} {change['path']}: {detail}")
        if not value["changes"]:
            typer.echo("No changes")
        if value.get("text"):
            typer.echo(value["text"], nl=not value["text"].endswith("\n"))
    elif "text" in value:
        if value["text"]:
            typer.echo(value["text"], nl=not value["text"].endswith("\n"))
        else:
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
                typer.echo(f"{state:<9} {count:>3}  {when:<16}  {entry['name']}{suffix}")
            else:
                typer.echo(f"{entry['name']}{suffix}")
    elif "state" in value and "resource" in value:
        count = value.get("history_count", 0)
        latest = value.get("latest_commit_at") or "-"
        typer.echo(
            f"{value['state']:<9} {value['resource']}  commits={count}  last={latest}"
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
        typer.echo(f"chronon: {exc}", err=True)
        raise typer.Exit(4) from exc
    except OSError as exc:
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
    agents_md: bool = typer.Option(
        False,
        "--agents-md",
        help=(
            "Also write/update a Chronon usage section in this directory's "
            "CHRONON.md (see 'chronon agents-md')."
        ),
    ),
    agents_md_file: str | None = typer.Option(
        None,
        "--agents-md-file",
        metavar="NAME",
        help="With --agents-md, use NAME instead of CHRONON.md (e.g. AGENTS.md).",
    ),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    _run(
        lambda: init_repository(
            directory, mode, register, agents_md_file or agents_md
        ),
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
    vault: str | None = VAULT_OPTION,
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    _run(
        lambda: {
            "resources": [
                ChrononRepository(vault=vault).add(resource) for resource in resources
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
    vault: str | None = VAULT_OPTION,
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    _run(
        lambda: ChrononRepository(vault=vault).commit(
            resource, message, author, expected_revision
        ),
        json_output,
    )


@app.command("diff")
def diff_command(
    resource: Path,
    from_ref: str = typer.Option("latest", "--from"),
    to_ref: str = typer.Option("working", "--to"),
    format: str = typer.Option("auto", "--format"),
    vault: str | None = VAULT_OPTION,
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    _run(
        lambda: ChrononRepository(vault=vault).diff(resource, from_ref, to_ref, format),
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
    vault: str | None = VAULT_OPTION,
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    _history(resource, limit, since, until, author, vault, json_output)


@app.command("history", hidden=True)
def history_command(
    resource: Path,
    limit: int | None = typer.Option(None, "--limit", "-n"),
    since: str | None = typer.Option(None, "--since"),
    until: str | None = typer.Option(None, "--until"),
    author: str | None = typer.Option(None, "--author"),
    vault: str | None = VAULT_OPTION,
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    _history(resource, limit, since, until, author, vault, json_output)


@app.command()
def status(
    resource: Path | None = typer.Argument(None),
    vault: str | None = VAULT_OPTION,
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    _run(
        lambda: (
            ChrononRepository(vault=vault).status(resource)
            if resource
            else ChrononRepository(vault=vault).list_resources()
        ),
        json_output,
    )


@app.command("list")
def list_command(
    vault: str | None = VAULT_OPTION, json_output: bool = typer.Option(False, "--json")
) -> None:
    _run(lambda: ChrononRepository(vault=vault).list_resources(), json_output)


@app.command("read")
def read_command(
    resource: Path,
    at: str = typer.Option("working", "--at"),
    parsed: bool = typer.Option(False, "--parsed"),
    vault: str | None = VAULT_OPTION,
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    def action() -> Any:
        result = ChrononRepository(vault=vault).read(
            resource, at, "parsed" if parsed else "raw"
        )
        if not parsed and not json_output:
            return result["content"]
        return result

    _run(action, json_output)


@ls_app.command()
def chronon_ls(
    directory: Path = typer.Argument(Path("."), help="Directory to list."),
    long_output: bool = typer.Option(
        False,
        "--long",
        "-l",
        help=(
            "Add columns: state, revision count, last commit time, name "
            "(like `ls -l`'s mode/nlink/mtime, but self-describing here in --help)."
        ),
    ),
    vault: str | None = VAULT_OPTION,
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """List immediate entries that contain Chronon-managed files."""

    def action() -> dict[str, Any]:
        if vault:
            return ChrononRepository(vault=vault).list_directory(
                directory, long_output
            )
        target = directory.resolve()
        return ChrononRepository(target).list_directory(target, long_output)

    _run(action, json_output)


# `chronon-ls`(별도 바이너리)와 별개로 `chronon ls`(서브커맨드)로도 쓸 수 있게 메인 app에도 등록한다.
# `app.add_typer(ls_app, name="ls")`는 안 된다 — ls_app이 단일 명령이라도 마운트되면 Typer가
# 함수 이름(chronon_ls → "chronon-ls")을 그대로 하위 커맨드 이름으로 남겨 `chronon ls chronon-ls`가
# 돼버린다. 같은 함수를 메인 app에 "ls" 라는 이름으로 직접 한 번 더 등록해야 `chronon ls`가 된다.
app.command("ls")(chronon_ls)


@cat_app.command()
def chronon_cat(
    resource: Path = typer.Argument(..., help="Managed file to read."),
    at: str = typer.Option("working", "--at", help="Revision to read."),
    vault: str | None = VAULT_OPTION,
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Write a managed file revision to standard output."""

    def action() -> Any:
        target = resource if vault else resource.resolve()
        result = ChrononRepository(None if vault else target, vault=vault).read(
            target, at, "raw"
        )
        return result if json_output else result["content"]

    _run(action, json_output)


@write_app.command()
def chronon_write(
    resource: Path = typer.Argument(..., help="Managed file to create or update."),
    content: str | None = typer.Option(None, "--content", help="Literal content."),
    stdin: bool = typer.Option(False, "--stdin", help="Read content from stdin."),
    scratch: bool = typer.Option(
        False, "--scratch", help="Save without creating a commit."
    ),
    message: str | None = typer.Option(None, "--message", "-m"),
    author: str | None = typer.Option(None, "--author"),
    expected_revision: str | None = typer.Option(None, "--if-match"),
    vault: str | None = VAULT_OPTION,
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Create or update a tracked UTF-8 text file."""
    sources = int(content is not None) + int(stdin)
    if sources != 1:
        typer.echo("chronon: choose exactly one of --content or --stdin", err=True)
        raise typer.Exit(4)
    modes = int(scratch) + int(message is not None)
    if modes != 1:
        typer.echo("chronon: choose exactly one of --scratch or --message", err=True)
        raise typer.Exit(4)

    def action() -> dict[str, Any]:
        target = resource if vault else resource.resolve()
        value = sys.stdin.read() if stdin else content or ""
        return ChrononRepository(None if vault else target, vault=vault).put(
            target, value, message, author, expected_revision
        )

    _run(action, json_output)


@commit_app.command()
def chronon_commit(
    resource: Path = typer.Argument(..., help="Managed scratch file to commit."),
    message: str = typer.Option(..., "--message", "-m"),
    expected_revision: str = typer.Option(..., "--if-match"),
    author: str | None = typer.Option(None, "--author"),
    vault: str | None = VAULT_OPTION,
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Commit exactly the scratch revision that was previously read."""

    def action() -> dict[str, Any]:
        target = resource if vault else resource.resolve()
        return ChrononRepository(None if vault else target, vault=vault).commit(
            target, message, author, expected_revision
        )

    _run(action, json_output)


@app.command("show")
def show_command(
    resource: Path,
    revision: str,
    parsed: bool = typer.Option(False, "--parsed"),
    vault: str | None = VAULT_OPTION,
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    def action() -> Any:
        result = ChrononRepository(vault=vault).read(
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
    message: str | None = typer.Option(None, "--message", "-m"),
    author: str | None = typer.Option(None, "--author"),
    expected_revision: str | None = typer.Option(None, "--if-match"),
    vault: str | None = VAULT_OPTION,
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    sources = sum(
        item is not None and item is not False for item in (content, file, stdin)
    )
    if sources != 1:
        typer.echo(
            "chronon: choose exactly one of --content, --file, or --stdin", err=True
        )
        raise typer.Exit(4)

    def action() -> dict[str, Any]:
        if file is not None:
            value = file.read_text(encoding="utf-8")
        elif stdin:
            value = sys.stdin.read()
        else:
            value = content or ""
        return ChrononRepository(vault=vault).write(
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
    vault: str | None = VAULT_OPTION,
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    _run(
        lambda: ChrononRepository(vault=vault).set_value(
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
    vault: str | None = VAULT_OPTION,
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    _run(
        lambda: ChrononRepository(vault=vault).unset_value(
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
    vault: str | None = VAULT_OPTION,
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    _run(
        lambda: ChrononRepository(vault=vault).path_history(
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
    vault: str | None = VAULT_OPTION,
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    _run(
        lambda: ChrononRepository(vault=vault).rollback(
            resource, revision, message, author, expected_revision
        ),
        json_output,
    )


@app.command()
def discard(
    resource: Path,
    force: bool = typer.Option(False, "--force"),
    expected_revision: str | None = typer.Option(None, "--if-match"),
    vault: str | None = VAULT_OPTION,
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    _run(
        lambda: ChrononRepository(vault=vault).discard(
            resource, force, expected_revision
        ),
        json_output,
    )


@app.command("accept")
def accept_command(
    resource: Path,
    vault: str | None = VAULT_OPTION,
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    _run(lambda: ChrononRepository(vault=vault).accept_foreign(resource), json_output)


@app.command()
def validate(
    resource: Path,
    vault: str | None = VAULT_OPTION,
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    _run(lambda: ChrononRepository(vault=vault).validate(resource), json_output)


@app.command("schema-register")
def schema_register(
    resource: Path,
    file: Path = typer.Option(..., "--file"),
    vault: str | None = VAULT_OPTION,
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    _run(
        lambda: ChrononRepository(vault=vault).register_schema(
            resource, json.loads(file.read_text(encoding="utf-8"))
        ),
        json_output,
    )


@app.command("agents-md")
def agents_md_command(
    filename: str = typer.Argument(
        "CHRONON.md",
        help="Doc file to write at the repo root (e.g. AGENTS.md, CLAUDE.md).",
    ),
    vault: str | None = VAULT_OPTION,
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Write or refresh this repository's agents doc with chronon usage.

    Writes CHRONON.md by default; pass another name (e.g. `chronon agents-md
    AGENTS.md`) to target that file instead.

    Meant as a lightweight substitute for MCP: an agent that reads this file
    (Claude Code and others do, automatically) learns the chronon CLI from
    plain Bash, without an MCP server having to be configured. Safe to re-run
    — only the marked chronon section is touched, everything else you or
    another tool wrote into the file is left alone.
    """
    _run(
        lambda: ChrononRepository(vault=vault).write_agents_md(filename),
        json_output,
    )


@app.command()
def version() -> None:
    typer.echo(__version__)


def main() -> None:
    argv = sys.argv[1:]
    # `init`, `add-vault`, `list-vaults`, `remove-vault` manage repositories or
    # the registry itself and don't declare --vault, so _command_accepts_vault
    # keeps the splice below from ever touching their own positional args.
    if argv and _command_accepts_vault(argv[0]):
        argv = _splice_positional_vault(argv, slot=1)
    app(args=argv, prog_name="chronon")


def ls_main() -> None:
    ls_app(args=_splice_positional_vault(sys.argv[1:], slot=0), prog_name="chronon-ls")


def cat_main() -> None:
    cat_app(
        args=_splice_positional_vault(sys.argv[1:], slot=0), prog_name="chronon-cat"
    )


def write_main() -> None:
    write_app(
        args=_splice_positional_vault(sys.argv[1:], slot=0), prog_name="chronon-write"
    )


def commit_main() -> None:
    commit_app(
        args=_splice_positional_vault(sys.argv[1:], slot=0), prog_name="chronon-commit"
    )


if __name__ == "__main__":
    main()
