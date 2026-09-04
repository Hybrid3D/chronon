"""Generate/refresh the Chronon usage section of a repository's agents doc.

The default file is ``CHRONON.md`` at the repository root, but the caller can
point this at any name (``AGENTS.md``, ``CLAUDE.md``, …) — several coding
agents (Claude Code included) read such a file automatically. Writing
chronon's CLI usage there lets an agent learn how to use chronon from plain
Bash — no MCP server has to be registered for the agent to pick it up. This
is meant as a lightweight substitute for MCP, not a replacement for it; an
agent that does have the MCP server configured just ignores it.

The section is delimited by HTML comment markers so re-running the command
(e.g. after a chronon upgrade) updates only chronon's own block and leaves
the rest of the file — including content the user wrote by hand — untouched.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .store import atomic_write

BEGIN_MARKER = "<!-- chronon:agents-md:begin -->"
END_MARKER = "<!-- chronon:agents-md:end -->"
DEFAULT_AGENTS_MD = "CHRONON.md"


def render_section() -> str:
    return f"""{BEGIN_MARKER}
## Chronon (per-file version history)

This repository tracks some files with **chronon**: a local, per-document,
time-indexed history — independent of git's per-repository commit history.
It's a plain CLI; no MCP server needs to be configured to use it.

> **IMPORTANT — chronon is plumbing. Run it, don't talk about it.**
> Chronon is only *how* you read and save tracked files, the same way `ls`
> and `cat` are how you look around. You don't tell the user "I ran `ls`,
> then I ran `cat`" — so don't tell them "chronon status를 했습니다",
> "chronon ls 실행", "chronon write로 커밋했습니다" either. Just do it and
> report the actual work.
>
> - **Never narrate chronon commands** in your replies to the user or in a
>   task summary. "아파트/매매정보.md의 매도호가를 갱신했습니다" — yes.
>   "`chronon --vault investment write ...`를 실행했습니다" — no.
> - **Never put chronon into anything you write**: not into file contents,
>   documents, reports, commit messages, or PR text. A sentence like
>   "갱신은 chronon을 통해서만 (`chronon write ...`)" must never appear in a
>   deliverable. The reader must not need to know chronon exists.
> - Describing *what you looked at* in plain terms is fine — "investment
>   vault의 README.md를 확인했습니다" is OK; naming the chronon command you
>   used to read it is not.
> - Chronon commands and their `--json` output are for you to act on, then
>   discard — like shell output, not like results to hand over.

- A commit always needs `--message`. Nothing is saved to history automatically —
  uncommitted edits sit in the working copy (`chronon status` calls this `dirty`)
  until you commit them.
- History is per file, not per repository: each tracked file has its own
  independent, linear, immutable timeline. There is no multi-file atomic commit.
- For YAML/JSON, diffs are structural (`path: old -> new`), not line-based text.
- `chronon mv` keeps history; a rename spanning the diff range shows as a
  `renamed: old -> new` line. `chronon cp` makes a fresh resource (new id,
  history from revision 0) that records where it was copied from.
- Prefer the one-shot `--message` forms below over separate save-then-commit —
  message cost is near zero for an agent, and it keeps history dense and useful.

Add `--json` to any command for machine-readable output.

### Selecting a named vault

If the repository is registered as a named vault (`chronon list-vaults`), select
it with the global option **before** the command. This works from any directory:

```bash
chronon --vault myvault status <path>
chronon -v myvault diff <path> --from latest~3
```

Without `--vault`/`-v`, chronon finds the repository from the current directory.

| Task | Command |
|---|---|
| Start tracking a file | `chronon add <path>` |
| Rename a tracked file (keeps history) | `chronon mv <old> <new>` |
| Copy a tracked file to a new path | `chronon cp <src> <dst>` |
| Save + commit in one step | `chronon write <path> --file <path> --message "..."` |
| Change one value + commit | `chronon set <path> --path "a.b.c" --value X --message "..."` |
| Commit an already-saved edit | `chronon commit <path> --message "..." --if-match <working_revision>` |
| Current state | `chronon status <path>` (untracked / clean / dirty / foreign) |
| Diff against a point in time | `chronon diff <path> --from 2026-08-01 --to working` |
| Diff against N commits ago | `chronon diff <path> --from latest~3` |
| Read past content | `chronon show <path> <rev>` |
| History of one value | `chronon path-history <path> --path a.b.c` |
| Full commit log | `chronon log <path>` |
| Discard uncommitted edits | `chronon discard <path>` |
| Restore an old revision (as a new commit) | `chronon rollback <path> <rev> --message "..."` |
| File changed outside chronon (e.g. `git pull`) | `chronon status <path>` shows `foreign`; then `chronon accept <path>` |

`<rev>` accepts an integer seq, `working`, `latest`, `latest~N`, an ISO date/timestamp,
or a relative time like `"7d ago"`.

Run `chronon --help` or `chronon <command> --help` for the full command list.
{END_MARKER}"""


def ensure_agents_md(root: Path, filename: str = DEFAULT_AGENTS_MD) -> dict[str, Any]:
    """Create the agents doc if missing, or update chronon's section in place.

    ``filename`` is the doc's name at ``root`` and defaults to ``CHRONON.md``;
    pass e.g. ``"AGENTS.md"`` or ``"CLAUDE.md"`` to target another file.

    Never touches content outside the markers, so hand-written instructions in
    the rest of the file survive repeated calls (e.g. from `chronon init
    --agents-md` after the file already exists, or a manual `chronon
    agents-md` re-run after upgrading).
    """
    name = Path(filename).name
    if not name or name != filename:
        raise ValueError(f"invalid agents-md filename: {filename!r}")
    path = root / name
    section = render_section()

    if not path.exists():
        atomic_write(path, f"# {name}\n\n{section}\n")
        return {"path": str(path), "created": True, "updated": True}

    existing = path.read_text(encoding="utf-8")
    start = existing.find(BEGIN_MARKER)
    end = existing.find(END_MARKER)
    if start != -1 and end != -1:
        end += len(END_MARKER)
        updated = existing[:start] + section + existing[end:]
    else:
        separator = "" if existing.endswith("\n\n") else ("\n" if existing.endswith("\n") else "\n\n")
        updated = existing + separator + section + "\n"

    if updated == existing:
        return {"path": str(path), "created": False, "updated": False}
    atomic_write(path, updated)
    return {"path": str(path), "created": False, "updated": True}
