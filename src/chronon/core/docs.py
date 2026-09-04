"""Generate/refresh Chronon guidance in an external agent working directory.

The default file is ``CHRONON.md`` in a caller-selected directory. That
directory need not be a Chronon vault: in the common case it is the external
workspace from which an agent accesses a registered vault. Callers that embed
the section in another guidance file may still select a different filename.

There are two variants. The generic section explains how to select a vault;
the vault-specific section fixes one registered vault name and puts that
selector into every example. Both teach an agent to use Chronon from plain
Bash, without requiring an MCP server.

The section is delimited by HTML comment markers so re-running the command
(e.g. after a chronon upgrade) updates only chronon's own block and leaves
the rest of the file — including content the user wrote by hand — untouched.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .errors import FileError, InvalidArgument
from .store import atomic_write

BEGIN_MARKER = "<!-- chronon:agents-md:begin -->"
END_MARKER = "<!-- chronon:agents-md:end -->"
DEFAULT_AGENTS_MD = "CHRONON.md"


def _render_section(vault: str | None) -> str:
    command = f"chronon --vault {vault}" if vault else "chronon"
    heading = f"Chronon vault `{vault}`" if vault else "Chronon"
    if vault:
        context = f"""This workspace uses the registered Chronon vault **`{vault}`**. All paths
below are relative to that vault's root, regardless of the current directory.
Always keep `--vault {vault}` before the subcommand.

Do not inspect or modify that vault with direct filesystem tools. Use
`{command} ls`, `{command} read`, and `{command} write` so Chronon can enforce
tracking, scratch safety, revision preconditions, and history."""
        selection = f"""### Selected vault

The vault is already selected for this workspace:

```bash
{command} ls .
{command} status
```

Do not substitute another vault unless the user explicitly changes the target."""
    else:
        context = """This workspace may use documents managed by **chronon**: a local,
per-document, time-indexed history independent of git. When the user identifies
a named vault, access its managed files through Chronon rather than direct
filesystem tools. Use `chronon ls`, `read`, and `write` so Chronon can enforce
tracking, scratch safety, revision preconditions, and history."""
        selection = """### Selecting a vault

If the user supplies a registered vault name, put the global selector before
every subcommand. This works from any directory:

```bash
chronon --vault <vault> ls .
chronon --vault <vault> status
```

Without `--vault`/`-v`, Chronon discovers a vault from the current directory.
Do not guess which named vault to use."""

    return f"""{BEGIN_MARKER}
## {heading} (per-file version history)

{context}

Chronon is a plain CLI; no MCP server needs to be configured to use it.

> **IMPORTANT — chronon is plumbing. Run it, don't talk about it.**
> Chronon is only *how* you read and save tracked files, the same way `ls`
> and `cat` are how you look around. You don't tell the user "I ran `ls`,
> then I ran `cat`" — so don't tell them "chronon status를 했습니다",
> "chronon ls 실행", "chronon write로 커밋했습니다" either. Just do it and
> report the actual work.
>
> - **Never narrate chronon commands** in your replies to the user or in a
>   task summary. "아파트/매매정보.md의 매도호가를 갱신했습니다" — yes.
>   "`{command} write ...`를 실행했습니다" — no.
> - **Never put chronon into anything you write**: not into file contents,
>   documents, reports, commit messages, or PR text. A sentence like
>   "갱신은 chronon을 통해서만 (`chronon write ...`)" must never appear in a
>   deliverable. The reader must not need to know chronon exists.
> - Describing *what you looked at* in plain terms is fine — "vault의
>   README.md를 확인했습니다" is OK; naming the chronon command you
>   used to read it is not.
> - Chronon commands and their `--json` output are for you to act on, then
>   discard — like shell output, not like results to hand over.

- A commit always needs `--message`. Nothing is saved to history automatically.
  A Chronon scratch edit is `dirty`; a normal editor or another program produces
  `foreign`. Both are uncommitted until you explicitly commit them.
- History is per file, not per repository: each tracked file has its own
  independent, linear, immutable timeline. There is no multi-file atomic commit.
- For YAML/JSON, diffs are structural (`path: old -> new`), not line-based text.
- `chronon mv` keeps history; a rename spanning the diff range shows as a
  `renamed: old -> new` line. `chronon cp` makes a fresh resource (new id,
  history from revision 0) that records where it was copied from.
- Prefer the one-shot `--message` forms below over separate save-then-commit —
  message cost is near zero for an agent, and it keeps history dense and useful.
- Before mutating a tracked file, read it or run `status --json`, retain the opaque
  `working_revision`, and pass it back as `--if-match`. On `revision_conflict`,
  re-read and reconcile; never retry a stale overwrite blindly.

Prefer `--json` when you need structured state or a `working_revision` token.

{selection}

| Task | Command |
|---|---|
| List managed files | `{command} ls [directory]` |
| Read current content | `{command} read <path>` |
| Start tracking a file | `{command} add <path>` |
| Rename a tracked file (keeps history) | `{command} mv <old> <new>` |
| Copy a tracked file to a new path | `{command} cp <src> <dst>` |
| Save scratch content without committing | `{command} write <path> --stdin --scratch --if-match <working_revision>` |
| Replace content + commit in one step | `{command} write <path> --stdin --message "..." --if-match <working_revision>` |
| Change one value + commit | `{command} set <path> --path "a.b.c" --value X --message "..." --if-match <working_revision>` |
| Commit an existing scratch edit | `{command} commit <path> --message "..." --if-match <working_revision>` |
| Current state | `{command} status <path>` (untracked / clean / dirty / foreign / missing) |
| Diff against a point in time | `{command} diff <path> --from 2026-08-01 --to working` |
| Diff against N commits ago | `{command} diff <path> --from latest~3` |
| Read past content | `{command} show <path> <rev>` |
| History of one value | `{command} path-history <path> --path a.b.c` |
| Full commit log | `{command} log <path>` |
| Discard uncommitted edits | `{command} discard <path>` |
| Restore an old revision (as a new commit) | `{command} rollback <path> <rev> --message "..."` |
| Accept an edit made outside Chronon | get `working_revision`, then `{command} accept <path> --if-match <working_revision>`; read again before the next write |

`<rev>` accepts an integer seq, `working`, `latest`, `latest~N`, an ISO date/timestamp,
or a relative time like `"7d ago"`.

Run `chronon --help` or `chronon <command> --help` for the full command list.
{END_MARKER}"""


def render_section() -> str:
    """Render generic guidance that explains how a vault is selected."""
    return _render_section(None)


def render_vault_section(vault: str) -> str:
    """Render guidance specialized for one registered vault name."""
    return _render_section(vault)


def ensure_agents_md(
    root: Path,
    filename: str = DEFAULT_AGENTS_MD,
    vault: str | None = None,
) -> dict[str, Any]:
    """Create the agents doc if missing, or update chronon's section in place.

    ``filename`` is the doc's name at ``root`` and defaults to ``CHRONON.md``;
    pass e.g. ``"AGENTS.md"`` or ``"CLAUDE.md"`` to target another file.

    Never touches content outside the markers, so hand-written instructions in
    the rest of the file survive repeated `chronon agents-md` calls.
    """
    root = Path(root).expanduser().resolve()
    if not root.is_dir():
        raise InvalidArgument(
            "agent instructions destination must be an existing directory",
            path=str(root),
        )
    name = Path(filename).name
    if not name or name != filename:
        raise InvalidArgument("invalid agent instructions filename", filename=filename)
    path = root / name
    section = render_vault_section(vault) if vault else render_section()

    if not path.exists():
        try:
            atomic_write(path, f"# {name}\n\n{section}\n")
        except OSError as exc:
            raise FileError("cannot write agent instructions", path=str(path)) from exc
        return {"path": str(path), "created": True, "updated": True}

    try:
        existing = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise FileError("cannot read agent instructions", path=str(path)) from exc
    start = existing.find(BEGIN_MARKER)
    end = existing.find(END_MARKER)
    marker_counts = (existing.count(BEGIN_MARKER), existing.count(END_MARKER))
    if marker_counts not in {(0, 0), (1, 1)} or (
        start != -1 and end != -1 and end < start
    ):
        raise InvalidArgument(
            "agent instructions contain malformed chronon markers",
            path=str(path),
            hint="repair or remove the chronon marker block, then retry",
        )
    if start != -1 and end != -1:
        end += len(END_MARKER)
        updated = existing[:start] + section + existing[end:]
    else:
        separator = (
            ""
            if existing.endswith("\n\n")
            else ("\n" if existing.endswith("\n") else "\n\n")
        )
        updated = existing + separator + section + "\n"

    if updated == existing:
        return {"path": str(path), "created": False, "updated": False}
    try:
        atomic_write(path, updated)
    except OSError as exc:
        raise FileError("cannot write agent instructions", path=str(path)) from exc
    return {"path": str(path), "created": False, "updated": True}
