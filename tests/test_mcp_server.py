import asyncio
from pathlib import Path

from chronon.api.operations import ChrononRepository, init_repository
from chronon.mcp_server import mcp


def test_mcp_exposes_manual_versioning_tools() -> None:
    tools = asyncio.run(mcp.list_tools())
    names = {tool.name for tool in tools}
    assert {
        "initialize_repository",
        "add_resource",
        "move_resource",
        "copy_resource",
        "put_resource",
        "commit_resource",
        "diff_resource",
        "history_resource",
        "list_directory",
        "register_schema",
        "write_agent_instructions",
    } <= names
    assert "lock_resource" not in names


def test_mcp_server_instructions_match_safe_tool_first_workflow() -> None:
    instructions = mcp.instructions or ""

    assert "Use these MCP tools" in instructions
    assert "not direct filesystem writes or the Chronon CLI" in instructions
    assert "working_revision" in instructions
    assert "expected_revision" in instructions
    assert "revision_conflict" in instructions
    assert "with an error field" in instructions


def test_mcp_tool_calls_shared_operations(tmp_path: Path, monkeypatch) -> None:
    init_repository(tmp_path)
    (tmp_path / "docs.yml").write_text("value: 1\n", encoding="utf-8")
    repository = ChrononRepository(tmp_path)
    repository.add("docs.yml")
    working_revision = repository.read("docs.yml")["working_revision"]
    monkeypatch.chdir(tmp_path)

    _, result = asyncio.run(
        mcp.call_tool(
            "commit_resource",
            {
                "resource": "docs.yml",
                "message": "initial",
                "expected_revision": working_revision,
            },
        )
    )
    assert result["committed"] is True
    assert result["commit"]["seq"] == 1


def test_mcp_returns_structured_domain_errors(tmp_path: Path, monkeypatch) -> None:
    init_repository(tmp_path)
    monkeypatch.chdir(tmp_path)
    _, result = asyncio.run(
        mcp.call_tool("status_resource", {"resource": "missing.yml"})
    )
    assert result["error"] == "resource_not_tracked"


def test_mcp_can_initialize_and_create_a_resource(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "vault"
    monkeypatch.chdir(tmp_path)

    _, initialized = asyncio.run(
        mcp.call_tool(
            "initialize_repository",
            {
                "directory": str(root),
            },
        )
    )
    assert initialized["created"] is True
    assert not (root / "CHRONON.md").exists()

    monkeypatch.chdir(root)
    _, created = asyncio.run(
        mcp.call_tool(
            "put_resource",
            {
                "resource": "notes.yml",
                "content": "value: 1\n",
                "message": "initial",
            },
        )
    )
    assert created["created"] is True
    assert created["committed"] is True

    _, listing = asyncio.run(mcp.call_tool("list_directory", {"include_status": True}))
    assert listing["entries"][0]["state"] == "clean"


def test_mcp_agent_instructions_error_is_structured(
    tmp_path: Path, monkeypatch
) -> None:
    init_repository(tmp_path)
    monkeypatch.chdir(tmp_path)
    _, result = asyncio.run(
        mcp.call_tool("write_agent_instructions", {"directory": "missing-directory"})
    )
    assert result["error"] == "invalid_argument"
