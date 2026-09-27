# CLI guide

Run `chronon COMMAND --help` for every option. Add `--json` to any command for
machine-readable output.

## Selecting a vault

```bash
chronon --vault knowledge status     # -v works too, before or after the subcommand
chronon set-vault knowledge          # pin this directory (writes .chronon-workspace)
chronon unset-vault
chronon read chronon://knowledge/notes.yml   # vault named inline in the resource
```

Without `--vault` or a pin, Chronon searches upward for `.chronon/config.toml`,
like Git, then falls back to a workspace pin. A `chronon://<vault>/<path>`
resource argument names its vault the same way `--vault` does — it works from
anywhere, even a directory with no cwd vault and no pin, and either one given
alongside a conflicting `--vault` (or another `chronon://` argument in the same
command) is rejected rather than silently resolved.

## Editing safely

Every mutation can take `--if-match <working_revision>`, obtained from a prior
`read --json` or `status --json`. It rejects the write if someone else changed
the file in between.

```bash
# Track and commit an existing file
chronon add config.yml
chronon commit config.yml -m "track initial configuration" --if-match '<rev>'

# Replace content (--content, --file, or --stdin)
chronon write note.md --content '# New text' -m "replace note" --if-match '<rev>'

# Change one YAML/JSON value
chronon set config.yml --path servers.web.port --value 9090 --type int \
  -m "move web service to port 9090" --if-match '<rev>'
```

`write` also creates and tracks a missing file, and takes exactly one of
`-m MESSAGE` (commit now) or `--scratch` (save uncommitted until `commit`).
There is no staging area: one commit covers exactly one file and always needs a
message.

## File states

| State | Meaning |
|---|---|
| `untracked` | Tracked by Chronon but no commits yet |
| `clean` | Matches the latest commit |
| `dirty` | Changed through Chronon, not committed |
| `foreign` | Changed outside Chronon (e.g. an editor) |
| `missing` | Working file deleted |

For a `foreign` change, either `commit` it as-is, `accept` it as a dirty
baseline to keep editing, or `discard --force` it to restore the last commit.

## History and recovery

```bash
chronon log config.yml
chronon diff config.yml --from latest~1 --to latest
chronon show config.yml 1
chronon path-history config.yml servers.web.port
chronon rollback config.yml 1 -m "restore original settings" --if-match '<rev>'
chronon mv config.yml config/web.yml     # keeps identity and history
chronon cp config/web.yml web.example.yml  # new resource, records its origin
```

`rollback` adds a new commit; history is never rewritten.

Revisions can be `1`, `working`, `latest`, `latest~3`, `2026-08-01`,
`2026-08-01T13:30:00+09:00`, or `7d ago` / `3h ago` / `30m ago`. YAML and JSON
diffs are structural by default (`--format auto|structural|text|both`).

## Validation

```bash
chronon schema-register config.json --file config.schema.json
chronon validate config.json
```

Once a JSON Schema (2020-12) is registered, every Chronon write is validated
before the file is replaced.

## Vault registry

```bash
chronon init ~/Documents/knowledge --register knowledge
chronon add-vault work /path/to/initialized/repository
chronon list-vaults
chronon remove-vault work                     # removes the name only
chronon admin vault-path work                 # human-only: show storage path
chronon admin set-vault-path work /new/path   # human-only: repoint, moves nothing
```

The registry lives in `%APPDATA%\chronon\vaults.toml` on Windows and
`~/.config/chronon/vaults.toml` (or `$XDG_CONFIG_HOME`) elsewhere; override the
directory with `CHRONON_CONFIG_HOME`. `add-vault` never overwrites an existing
name with a different path.

`list-vaults` and MCP `list_vaults` hide physical paths. The `admin` group is
not exposed over MCP, and generated agent instructions forbid agents from
invoking it. This is an instruction, not an access-control boundary.

## Command reference

| Command | Purpose |
|---|---|
| `init [DIR]` | Initialize a repository, optionally `--register NAME` |
| `add FILE...` | Start tracking existing files |
| `status [FILE]`, `list`, `ls [DIR]` | Show states and tracked files |
| `read FILE`, `show FILE REV` | Read working or historical content |
| `write FILE` | Replace (or create) content, optionally committing |
| `commit FILE` | Commit one working copy |
| `set` / `unset FILE` | Change a YAML/JSON path |
| `diff`, `log`, `path-history` | Inspect history |
| `mv`, `cp` | Rename or copy a resource |
| `rollback FILE REV` | Restore a revision as a new commit |
| `discard`, `accept` | Resolve uncommitted or foreign changes |
| `schema-register`, `validate` | JSON Schema validation |
| `agent-setup`, `agent-instructions` | Agent guidance ([details](agents.md)) |
| `add-vault`, `list-vaults`, `remove-vault` | Manage vault names |
| `set-vault`, `unset-vault` | Pin a workspace to a vault |
| `admin vault-path`, `admin set-vault-path` | Human-only registry administration |

Exit codes: `1` failed check, `3` lookup failure, `4` invalid arguments,
`5` nothing to commit, `6` protected foreign change, `7` missing/stale
precondition, `8` no state at the requested revision. JSON errors include a
stable `error` code.
