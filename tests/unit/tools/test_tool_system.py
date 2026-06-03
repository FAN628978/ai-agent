import asyncio
import sys

import pytest

from agent_system.models import ToolCall
from agent_system.tools import ToolRegistry, ToolRouter
from agent_system.tools.builtin import GrepSearchTool, ReadFileTool, ShellRunTool, WriteFileTool


def test_registry_registers_and_filters_schemas() -> None:
    registry = ToolRegistry()
    read_tool = ReadFileTool()
    write_tool = WriteFileTool()

    registry.register(read_tool)
    registry.register(write_tool)

    assert registry.get("file.read") is read_tool
    assert [schema.name for schema in registry.schemas(read_only=True)] == ["file.read"]
    assert [schema.name for schema in registry.schemas(read_only=False)] == ["file.write"]


def test_registry_rejects_duplicate_tools() -> None:
    registry = ToolRegistry()
    registry.register(ReadFileTool())

    with pytest.raises(ValueError, match="duplicate tool"):
        registry.register(ReadFileTool())


def test_router_returns_error_for_unknown_tool(tmp_path) -> None:
    router = ToolRouter(ToolRegistry(), tmp_path)
    call = ToolCall(id="call-1", name="missing.tool", arguments={})

    result = asyncio.run(router.invoke(call))

    assert result.ok is False
    assert result.error == "unknown tool: missing.tool"


def test_file_read_and_write_tools(tmp_path) -> None:
    registry = ToolRegistry()
    registry.register(WriteFileTool())
    registry.register(ReadFileTool())
    router = ToolRouter(registry, tmp_path)

    write = asyncio.run(
        router.invoke(
            ToolCall(
                id="write-1",
                name="file.write",
                arguments={"path": "notes/hello.txt", "content": "hello"},
            )
        )
    )
    read = asyncio.run(
        router.invoke(
            ToolCall(
                id="read-1",
                name="file.read",
                arguments={"path": "notes/hello.txt"},
            )
        )
    )

    assert write.ok is True
    assert write.content["bytes_written"] == 5
    assert read.ok is True
    assert read.content["content"] == "hello"


def test_file_tool_blocks_workspace_escape(tmp_path) -> None:
    registry = ToolRegistry()
    registry.register(ReadFileTool())
    router = ToolRouter(registry, tmp_path)

    result = asyncio.run(
        router.invoke(
            ToolCall(
                id="read-1",
                name="file.read",
                arguments={"path": "../outside.txt"},
            )
        )
    )

    assert result.ok is False
    assert "path escapes workspace" in result.error


def test_grep_search_tool_finds_matches(tmp_path) -> None:
    (tmp_path / "a.txt").write_text("alpha\nbeta\n", encoding="utf-8")
    (tmp_path / "b.txt").write_text("gamma\nalphabet\n", encoding="utf-8")
    registry = ToolRegistry()
    registry.register(GrepSearchTool())
    router = ToolRouter(registry, tmp_path)

    result = asyncio.run(
        router.invoke(
            ToolCall(
                id="grep-1",
                name="grep.search",
                arguments={"pattern": "alpha", "max_results": 2},
            )
        )
    )

    assert result.ok is True
    assert result.content["count"] == 2
    assert [match["line"] for match in result.content["matches"]] == ["alpha", "alphabet"]


def test_shell_run_tool_is_disabled_by_default(tmp_path) -> None:
    registry = ToolRegistry()
    registry.register(ShellRunTool())
    router = ToolRouter(registry, tmp_path)

    result = asyncio.run(
        router.invoke(
            ToolCall(
                id="shell-1",
                name="shell.run",
                arguments={"command": "echo hello"},
            )
        )
    )

    assert result.ok is False
    assert result.error == "shell.run is disabled"


def test_shell_run_tool_executes_when_enabled(tmp_path) -> None:
    registry = ToolRegistry()
    registry.register(ShellRunTool(enabled=True))
    router = ToolRouter(registry, tmp_path)
    command = f'"{sys.executable}" -c "print(123)"'

    result = asyncio.run(
        router.invoke(
            ToolCall(
                id="shell-1",
                name="shell.run",
                arguments={"command": command},
            )
        )
    )

    assert result.ok is True
    assert result.content["returncode"] == 0
    assert result.content["stdout"].strip() == "123"


def test_shell_run_tool_times_out(tmp_path) -> None:
    registry = ToolRegistry()
    registry.register(ShellRunTool(enabled=True))
    router = ToolRouter(registry, tmp_path)
    command = f'"{sys.executable}" -c "import time; time.sleep(2)"'

    result = asyncio.run(
        router.invoke(
            ToolCall(
                id="shell-1",
                name="shell.run",
                arguments={"command": command, "timeout_s": 0.1},
            )
        )
    )

    assert result.ok is False
    assert result.error == "shell command timed out after 0.1s"
