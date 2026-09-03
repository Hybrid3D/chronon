import asyncio
from pathlib import Path

from chronon.api.operations import ChrononRepository, init_repository
from chronon.mcp_server import mcp


def test_mcp_exposes_manual_versioning_tools() -> None:
    tools = asyncio.run(mcp.list_tools())
    names = {tool.name for tool in tools}
    assert {
        "add_resource",
        "commit_resource",
        "diff_resource",
        "history_resource",
    } <= names
    assert "lock_resource" not in names


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
