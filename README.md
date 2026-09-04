# Chronon

Chronon is a local version history for individual UTF-8 documents. Each tracked
file gets its own linear, immutable timeline, time-based lookup, and structural
diffs for YAML and JSON. It works alongside Git, but does not call or replace
Git.

Chronon can be used in three ways:

- by a person through the `chronon` CLI;
- by an AI agent through the same CLI, guided by a generated `CHRONON.md`; or
- by an AI client through the local stdio MCP server, `chronon-mcp`.

> **Project status:** alpha. Manual commit mode is implemented. `--mode auto` is
> reserved but intentionally returns `not_implemented`. Before relying on
> Chronon as the only copy of important history, read [Data and backups](#data-and-backups).

## Requirements

- Python 3.11 or newer
- Windows 10/11, Linux, WSL2, or macOS
- UTF-8 text files; YAML, JSON, Markdown, and plain text are the primary formats

## Installation

[`pipx`](https://pipx.pypa.io/latest/how-to/install-pipx.html) is recommended for
an end-user CLI installation. It gives Chronon its own Python environment while
putting all commands on `PATH`.

The package name is `chronon-vcs`; the installed commands are:

```text
chronon
chronon-mcp
```

`chronon` is the single human/CLI-agent entry point. `chronon-mcp` is optional
and is only needed by clients that integrate through MCP instead of a shell.

### macOS

Install Python and pipx, then install from a checked-out copy of this repository:

```bash
brew install python pipx
pipx ensurepath
# Open a new terminal after ensurepath.

# Clone this repository into a directory named chronon, then:
cd chronon
pipx install .
chronon --version
```

If Python 3.11+ is already installed, only pipx and the final three commands are
needed.

### Linux

Ubuntu 23.04+/Debian 12+:

```bash
sudo apt update
sudo apt install pipx
pipx ensurepath
# Open a new shell after ensurepath.

# Clone this repository into a directory named chronon, then:
cd chronon
pipx install .
chronon --version
```

Fedora:

```bash
sudo dnf install pipx
pipx ensurepath
# Clone this repository into a directory named chronon, then:
cd chronon
pipx install .
chronon --version
```

Do not install into an OS-managed Python with `sudo pip`. On distributions that
enforce PEP 668, use the distribution's pipx package or the alternatives in the
[official pipx instructions](https://pipx.pypa.io/latest/how-to/install-pipx.html).

### WSL2

Use the Linux instructions inside WSL, even if Python or pipx is also installed
on Windows. Keep the Chronon installation and active vault on the same side of
the Windows/WSL boundary. For the best filesystem behavior and performance, a
path below the WSL home directory (for example `~/vaults/notes`) is preferable
to `/mnt/c/...`.

```bash
sudo apt update
sudo apt install pipx
pipx ensurepath
# Clone this repository into a directory named chronon, then:
cd chronon
pipx install .
chronon --version
```

### Windows (PowerShell)

Install Python 3.11+ from [python.org](https://www.python.org/downloads/windows/)
and enable the installer option that makes the Python launcher available. Then:

```powershell
py -m pip install --user pipx
py -m pipx ensurepath
# Close and reopen PowerShell after ensurepath.

# Clone this repository into a directory named chronon, then:
Set-Location chronon
pipx install .
chronon --version
```

If `pipx` is still not found after reopening PowerShell, follow the PATH step in
the [official Windows pipx instructions](https://pipx.pypa.io/latest/how-to/install-pipx.html#windows).

### PyPI installation after a release

Once `chronon-vcs` has been published to PyPI, installation becomes:

```bash
pipx install chronon-vcs
```

This repository is not published by the setup in this branch. Creating a GitHub
repository or publishing a package remains a separate, deliberate release step.

## Quick start

Initialize a directory and register a global name for it in one operation:

```bash
mkdir -p "$HOME/Documents/my-notes"
chronon init "$HOME/Documents/my-notes" --register notes
```

On PowerShell:

```powershell
New-Item -ItemType Directory -Force "$HOME\Documents\my-notes"
chronon init "$HOME\Documents\my-notes" --register notes
```

Create a file using any editor, start tracking it, observe its revision token,
and make the first commit:

```bash
printf 'title: First note\nstatus: draft\n' > "$HOME/Documents/my-notes/note.yml"
chronon --vault notes add note.yml
chronon --vault notes status note.yml --json
chronon --vault notes commit note.yml \
  --message "add first note" \
  --if-match '<working_revision from status>'
```

PowerShell equivalent for the file creation step:

```powershell
@"
title: First note
status: draft
"@ | Set-Content -Encoding utf8 "$HOME\Documents\my-notes\note.yml"
```

The `working_revision` value is an opaque compare-and-swap token. Passing it to
`--if-match` prevents a person or another agent from overwriting content that
changed after it was read.

## Working from a different directory

Vault registration is designed for this case. The initialization target does
not have to be the current directory:

```bash
cd "$HOME/work/client-app"

# Initialize a separate directory, register it as "knowledge", and create
# AI guidance there, without leaving client-app.
chronon init "$HOME/Documents/team-knowledge" \
  --register knowledge \
  --agents-md

chronon list-vaults
chronon --vault knowledge status
chronon --vault knowledge ls -l
```

The global `--vault`/`-v` option goes before the subcommand:

```bash
chronon --vault knowledge diff architecture.yml
chronon -v knowledge log architecture.yml
```

Without a vault option, Chronon searches upward from the current directory for
the nearest `.chronon/config.toml`, similar to Git repository discovery.

### Vault registry location

Vault names are per-user, not stored inside a vault:

- Windows: `%APPDATA%\chronon\vaults.toml`
- Linux, WSL, and macOS: `$XDG_CONFIG_HOME/chronon/vaults.toml` when
  `XDG_CONFIG_HOME` is set, otherwise `~/.config/chronon/vaults.toml`

Set `CHRONON_CONFIG_HOME` to override the directory on any platform. This is
also useful for isolated tests and automation.

```bash
chronon add-vault work /absolute/path/to/an/initialized/repository
chronon list-vaults
chronon remove-vault work  # removes only the name; files and history remain
```

## Everyday CLI workflow

### Track and commit an existing file

```bash
chronon add config.yml
chronon status config.yml --json
chronon commit config.yml -m "track initial configuration" \
  --if-match '<working_revision>'
```

`add` begins tracking; there is no staging area. A commit snapshots exactly one
file and always requires a message. The state name `untracked` is retained for
compatibility and means “tracked by Chronon but with zero commits,” not that
`add` failed.

### Make a structured change

```bash
chronon status config.yml --json
chronon set config.yml \
  --path servers.web.port \
  --value 9090 \
  --type int \
  --message "move web service to port 9090" \
  --if-match '<working_revision>'

chronon diff config.yml --from latest~1 --to latest
chronon path-history config.yml servers.web.port
```

Supported value types are inferred as YAML by default, or can be selected with
`--type str|int|float|bool|null|json`. `set` and `unset` work on YAML and JSON.

### Replace complete content

For a tracked file, provide exactly one content source:

```bash
chronon write note.md --content '# New text' -m "replace note"
chronon write note.md --file prepared-note.md -m "replace from prepared file"
printf '# Generated text\n' | chronon write note.md --stdin -m "replace note"
```

When the current state is `dirty`, include the revision returned by the preceding
read or status:

```bash
revision=$(chronon status note.md --json | python -c \
  'import json,sys; print(json.load(sys.stdin)["working_revision"])')
printf '# Final text\n' | chronon write note.md --stdin -m "finish note" \
  --if-match "$revision"
```

`chronon write` also creates a missing path and starts tracking it in one
operation:

```bash
printf 'first line\n' | chronon write notes/new.txt --stdin --scratch
chronon read notes/new.txt --json
chronon commit notes/new.txt -m "add note" --if-match '<working_revision>'
```

`chronon write` refuses to overwrite an existing untracked path.

### Normal editor and external changes

An edit made outside Chronon is reported as `foreign`. The content is not lost
or automatically accepted.

To commit exactly the external content you inspected:

```bash
chronon status config.yml --json
chronon validate config.yml
chronon commit config.yml -m "accept reviewed editor change" \
  --if-match '<working_revision>'
```

To accept it as an uncommitted Chronon baseline and continue editing:

```bash
chronon accept config.yml --if-match '<working_revision>'
chronon status config.yml --json  # read the new token before another write
```

To discard changes and restore the latest commit:

```bash
chronon discard config.yml --if-match '<working_revision>'
chronon discard config.yml --force --if-match '<working_revision>'  # foreign too
```

`--force` may destroy an external edit. A supplied revision is always checked.

### Move, copy, inspect, and restore

```bash
chronon mv docs.yml config/web.yml
chronon cp config/web.yml config/web.example.yml

chronon log config/web.yml
chronon show config/web.yml 1
chronon diff config/web.yml --from 1 --to working --format both
chronon rollback config/web.yml 1 -m "restore original settings" \
  --if-match '<working_revision>'
```

- `mv` preserves the resource ID, full history, path timeline, and schema.
- `cp` creates a new resource ID and empty history, while recording its origin.
- `rollback` restores old content as a new commit; it does not rewrite history.
- If a tracked working file is deleted, `status` reports `missing` and `discard`
  can restore its latest committed content.

### Revisions and diffs

Accepted revision specifications:

```text
1
working
latest
latest~3
2026-08-01
2026-08-01T13:30:00+09:00
7d ago
3h ago
30m ago
```

A date without a time means UTC midnight. YAML and JSON use structural diff by
default, so key ordering and indentation-only changes disappear. Other text
files use a unified text diff. `--format` accepts `auto`, `structural`, `text`,
or `both`.

### Validation with JSON Schema

```bash
chronon schema-register config.json --file config.schema.json
chronon validate config.json
```

The schema itself must be valid JSON Schema 2020-12, and registration fails if
the current document does not satisfy it. Future Chronon writes are validated
before the working file is replaced.

## CLI command reference

Run `chronon COMMAND --help` for every option.

| Command | Purpose |
|---|---|
| `init [DIR]` | Initialize a manual repository; optionally register a vault and generate agent guidance |
| `add FILE...` | Start tracking existing files |
| `status [FILE]` | Show one or all states: `untracked`, `clean`, `dirty`, `foreign`, `missing` |
| `list` | List all tracked resources and states |
| `ls [DIR]` | List immediate tracked children |
| `read FILE` | Read working or historical content |
| `show FILE REV` | Read one historical revision |
| `write FILE` | Replace an existing tracked working copy, optionally committing it |
| `commit FILE` | Commit exactly one working copy |
| `set FILE` / `unset FILE` | Change a YAML/JSON path |
| `diff FILE` | Compare two revisions |
| `log FILE` | List immutable commits, newest first |
| `path-history FILE PATH` | Show commits that changed one structured value |
| `mv SRC DST` | Rename while preserving identity and history |
| `cp SRC DST` | Copy into a new independent resource |
| `rollback FILE REV` | Restore a revision as a new commit |
| `discard FILE` | Restore the latest committed content |
| `accept FILE` | Accept a foreign edit as the current dirty baseline |
| `schema-register FILE` | Attach a JSON Schema |
| `validate FILE` | Validate current content |
| `agents-md [NAME]` | Create or refresh AI CLI guidance |
| `add-vault`, `list-vaults`, `remove-vault` | Manage global vault names |

Use `chronon --version` (or `chronon -V`) to print the installed version. Add
`--json` for machine-readable output. Domain errors also become JSON and
include a stable `error` code. Common exit codes are: `3` for repository/file
lookup, `4` for invalid arguments, `5` for nothing to commit, `6` for protected
foreign changes, `7` for a missing/stale precondition, and `8` when no state
exists at a requested revision.

## Using Chronon with an AI through `CHRONON.md`

Generate the file during initialization or later:

```bash
chronon init "$HOME/Documents/team-knowledge" \
  --register knowledge \
  --agents-md

# Equivalent later command:
chronon --vault knowledge agents-md
```

The generated section explains safe reads, revision preconditions, commits,
structured edits, and vault selection. It is bounded by these markers:

```html
<!-- chronon:agents-md:begin -->
<!-- chronon:agents-md:end -->
```

Re-running `agents-md` updates only that section and preserves everything else
in the file. You can prepend project-specific instructions, for example:

```markdown
# Knowledge vault instructions

- Preserve the existing document language and headings.
- Validate YAML before committing it.
- Use concise commit messages that describe the content change.
```

Whether an AI reads `CHRONON.md` automatically depends on the client. Start the
agent in the vault directory, attach the file, or name its absolute path in the
prompt. A complete prompt from another directory can be:

```text
First read ~/Documents/team-knowledge/CHRONON.md and follow it. Work in the
registered Chronon vault named "knowledge". Inspect architecture.yml, update the
web port to 9090, validate it, review the diff, and commit the change with a
concise message. If a decision is not material, use your recommended default and
record the assumption in decisions.md.
```

A well-behaved CLI agent should follow this sequence:

1. Read `status --json` or `read --json` and retain `working_revision`.
2. Make the smallest valid change.
3. Pass the retained token as `--if-match` on mutation.
4. Inspect `diff` and `validate`.
5. Commit with a meaningful message; never leave important work only as scratch.
6. On `revision_conflict`, re-read and reconcile instead of retrying blindly.

For clients that automatically read another filename, write the same managed
section there:

```bash
chronon --vault knowledge agents-md AGENTS.md
chronon --vault knowledge agents-md CLAUDE.md
```

## Using Chronon with an AI through MCP

`chronon-mcp` is a local stdio MCP server. The MCP host launches it as a child
process; it is not a web service and should not be started in a terminal for
interactive use. A generic client configuration is:

```json
{
  "mcpServers": {
    "chronon": {
      "command": "/absolute/path/to/chronon-mcp",
      "args": []
    }
  }
}
```

Find the executable after pipx installation:

```bash
command -v chronon-mcp
```

```powershell
(Get-Command chronon-mcp).Source
```

An absolute command path is recommended for GUI clients, which often inherit a
smaller `PATH` than a terminal. Each repository tool accepts an optional `vault`
name, so one server can work with registered vaults regardless of its startup
directory.

The MCP surface supports the full working flow:

- setup: `initialize_repository`, `list_vaults`, `add_vault`, `remove_vault`,
  `write_agent_instructions`;
- discovery/read: `list_resources`, `list_directory`, `status_resource`,
  `read_resource`, `diff_resource`, `history_resource`, `path_history`;
- write: `put_resource`, `add_resource`, `write_resource`, `set_value`,
  `unset_value`, `commit_resource`, `move_resource`, `copy_resource`;
- recovery/validation: `rollback_resource`, `discard_changes`,
  `accept_foreign`, `validate_resource`, `register_schema`.

MCP tools return domain failures as structured objects with an `error` field.
Agents should treat that field as failure even when the MCP transport call itself
succeeds. For concurrent safety, read first and pass `working_revision` as
`expected_revision` on later mutations.

The default stdio behavior follows the
[official MCP Python SDK transport guidance](https://github.com/modelcontextprotocol/python-sdk/blob/main/docs/run/index.md).

## Data and backups

Initialization creates:

```text
.chronon/
├── config.toml
├── locks/
├── resources/        # descriptor, state, commit index, immutable snapshots
└── schemas/
```

Chronon adds `/.chronon/` to the vault's `.gitignore`. Therefore Chronon history
is local by default and is **not** pushed with the surrounding Git repository.
Back up the working files and their `.chronon` directory together if the history
matters. Chronon does not encrypt content; snapshots contain the same sensitive
text as the working document.

Resource writes are atomic, and per-resource operations plus vault-registry
updates use inter-process locks on Windows, Linux, WSL, and macOS. A commit is
file-scoped; there is no atomic multi-file transaction.

## Development and tests

Create an isolated environment from the repository root:

```bash
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\Activate.ps1
python -m pip install -e '.[dev]'
```

Run the same checks used by CI:

```bash
python -m ruff check .
python -m ruff format --check .
python -m pytest --cov=chronon --cov-report=term-missing
python -m pip_audit . --skip-editable
python -m build
python -m twine check dist/*
```

The GitHub Actions workflow tests Python 3.11–3.14, including native Windows and
macOS jobs, enforces branch-aware coverage, checks formatting and dependencies,
tests the declared minimum dependency versions, builds both wheel and source
distributions, and installs the built wheel for a smoke test. See
[CONTRIBUTING.md](CONTRIBUTING.md) for the test layout.

## License

[MIT](LICENSE)
