# Contributing to Chronon

## Development setup

Chronon supports Python 3.11 and newer. Use a virtual environment rather than a
system Python installation:

```bash
python3 -m venv .venv
source .venv/bin/activate        # PowerShell: .venv\Scripts\Activate.ps1
python -m pip install -e '.[dev]'
```

## Test layout

- `tests/test_operations.py`: public repository operations, safety preconditions,
  validation, recovery, and multi-process commit serialization
- `tests/test_cli.py`: human and machine-readable CLI behavior
- `tests/test_mcp_server.py`: MCP tool inventory, parity, calls, and structured errors
- `tests/test_store.py`: initialization, discovery, path confinement, and metadata
  integrity
- `tests/test_integrity.py`: corrupt metadata, snapshot confinement, and format
  compatibility failures
- `tests/test_vaults.py`: registry behavior, platform paths, and multi-process updates
- `tests/test_move_copy.py`: stable identities, path history, lineage, and schemas
- `tests/test_path_diff.py`: structured paths and diffs
- `tests/test_revspec.py`: numeric, time-based, and relative revision resolution
- `tests/test_agents_md.py`: generated guidance and marker-preserving refreshes

Tests must not access a user's real vault registry. Set `CHRONON_CONFIG_HOME` to
a temporary directory in every test that adds or removes vaults.

## Required checks

```bash
python -m ruff check .
python -m ruff format --check .
python -m pytest --cov=chronon --cov-report=term-missing
python -m pip_audit . --skip-editable
python -m build
python -m twine check dist/*
```

Coverage includes branches and must remain at or above the threshold in
`pyproject.toml`. The dependency audit checks the runtime dependency graph
against published vulnerability advisories. New behavior should be exercised
through the public operation layer and, when exposed there, through its CLI or
MCP adapter.

## Cross-platform rules

- Use `pathlib.Path`; do not construct paths with hard-coded `/` or `\`.
- Keep stored resource paths POSIX-style for portable metadata.
- Any shared mutation must hold an inter-process lock, not only a thread lock.
- Do not assume `fcntl`, Bash, symlinks, or executable permission bits exist on
  Windows.
- Preserve UTF-8 and existing file permissions where the platform supports them.

GitHub Actions runs the suite on Linux, native Windows, and macOS. A local pass
on one OS is necessary but not sufficient for changes to storage or locking.
