import asyncio
import sys

import pytest

from agent_system.models import ToolCall
from agent_system.tools import ToolPermissionPolicy, ToolRegistry, ToolRouter
from agent_system.tools.builtin import BashTool, EditFileTool, GlobTool, GrepSearchTool, ReadFileTool, WriteFileTool


def test_registry_registers_and_filters_schemas() -> None:
    registry = ToolRegistry()
    read_tool = ReadFileTool()
    write_tool = WriteFileTool()

    registry.register(read_tool)
    registry.register(write_tool)

    assert registry.get("Read") is read_tool
    assert [schema.name for schema in registry.schemas(read_only=True)] == ["Read"]
    assert [schema.name for schema in registry.schemas(read_only=False)] == ["Write"]


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


def test_read_and_write_tools(tmp_path) -> None:
    registry = ToolRegistry()
    registry.register(WriteFileTool())
    registry.register(ReadFileTool())
    router = ToolRouter(registry, tmp_path)

    write = asyncio.run(
        router.invoke(
            ToolCall(
                id="write-1",
                name="Write",
                arguments={"path": "notes/hello.txt", "content": "hello"},
            )
        )
    )
    read = asyncio.run(
        router.invoke(
            ToolCall(
                id="read-1",
                name="Read",
                arguments={"path": "notes/hello.txt"},
            )
        )
    )

    assert write.ok is True
    assert write.content["bytes_written"] == 5
    assert read.ok is True
    assert read.content["content"] == "hello"


def test_read_tool_blocks_workspace_escape(tmp_path) -> None:
    registry = ToolRegistry()
    registry.register(ReadFileTool())
    router = ToolRouter(registry, tmp_path)

    result = asyncio.run(
        router.invoke(
            ToolCall(
                id="read-1",
                name="Read",
                arguments={"path": "../outside.txt"},
            )
        )
    )

    assert result.ok is False
    assert "path escapes workspace" in result.error


def test_tool_call_can_require_approval(tmp_path) -> None:
    (tmp_path / "notes.txt").write_text("hello", encoding="utf-8")
    registry = ToolRegistry()
    registry.register(ReadFileTool())
    router = ToolRouter(registry, tmp_path)

    result = asyncio.run(
        router.invoke(
            ToolCall(
                id="read-1",
                name="Read",
                arguments={"path": "notes.txt"},
                requires_approval=True,
            )
        )
    )

    assert result.ok is False
    assert result.error == "approval required"
    assert result.content["reason"] == "tool call requires approval"


def test_edit_tool_replaces_unique_text(tmp_path) -> None:
    (tmp_path / "notes.txt").write_text("hello agent", encoding="utf-8")
    registry = ToolRegistry()
    registry.register(EditFileTool())
    router = ToolRouter(registry, tmp_path)

    result = asyncio.run(
        router.invoke(
            ToolCall(
                id="edit-1",
                name="Edit",
                arguments={"path": "notes.txt", "old_string": "agent", "new_string": "runtime"},
            )
        )
    )

    assert result.ok is True
    assert result.content["replacements"] == 1
    assert (tmp_path / "notes.txt").read_text(encoding="utf-8") == "hello runtime"


def test_edit_tool_rejects_ambiguous_replacement_without_replace_all(tmp_path) -> None:
    (tmp_path / "notes.txt").write_text("x x", encoding="utf-8")
    registry = ToolRegistry()
    registry.register(EditFileTool())
    router = ToolRouter(registry, tmp_path)

    result = asyncio.run(
        router.invoke(
            ToolCall(
                id="edit-1",
                name="Edit",
                arguments={"path": "notes.txt", "old_string": "x", "new_string": "y"},
            )
        )
    )

    assert result.ok is False
    assert "multiple times" in result.error


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
                name="Grep",
                arguments={"pattern": "alpha", "max_results": 2},
            )
        )
    )

    assert result.ok is True
    assert result.content["count"] == 2
    assert [match["line"] for match in result.content["matches"]] == ["alpha", "alphabet"]


def test_glob_tool_finds_paths(tmp_path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("print(1)", encoding="utf-8")
    (tmp_path / "README.md").write_text("hello", encoding="utf-8")
    registry = ToolRegistry()
    registry.register(GlobTool())
    router = ToolRouter(registry, tmp_path)

    result = asyncio.run(
        router.invoke(
            ToolCall(
                id="glob-1",
                name="Glob",
                arguments={"pattern": "**/*.py"},
            )
        )
    )

    assert result.ok is True
    assert result.content["count"] == 1
    assert result.content["matches"][0]["relative_path"] == "src/app.py"


def test_shell_run_tool_is_disabled_by_default(tmp_path) -> None:
    registry = ToolRegistry()
    registry.register(BashTool())
    router = ToolRouter(registry, tmp_path)

    result = asyncio.run(
        router.invoke(
            ToolCall(
                id="shell-1",
                name="Bash",
                arguments={"command": "echo hello"},
            )
        )
    )

    assert result.ok is False
    assert result.error == "shell execution is denied by policy"
    assert result.metadata["audit"]["status"] == "denied"


def test_shell_run_tool_requires_approval_when_enabled(tmp_path) -> None:
    registry = ToolRegistry()
    registry.register(BashTool(enabled=True))
    router = ToolRouter(
        registry,
        tmp_path,
        permission_policy=ToolPermissionPolicy(default_shell="allow"),
    )

    result = asyncio.run(
        router.invoke(
            ToolCall(
                id="shell-1",
                name="Bash",
                arguments={"command": "echo hello"},
            )
        )
    )

    assert result.ok is False
    assert result.error == "approval required"
    assert result.content["approval_required"] is True
    assert result.metadata["audit"]["status"] == "approval_required"


def test_shell_run_tool_executes_when_enabled(tmp_path) -> None:
    registry = ToolRegistry()
    registry.register(BashTool(enabled=True))
    router = ToolRouter(
        registry,
        tmp_path,
        permission_policy=ToolPermissionPolicy(default_shell="allow"),
    )
    command = f'"{sys.executable}" -c "print(123)"'

    result = asyncio.run(
        router.invoke(
            ToolCall(
                id="shell-1",
                name="Bash",
                arguments={"command": command},
                approved=True,
            )
        )
    )

    assert result.ok is True
    assert result.content["returncode"] == 0
    assert result.content["stdout"].strip() == "123"
    assert result.metadata["audit"]["status"] == "success"


def test_shell_run_tool_times_out(tmp_path) -> None:
    registry = ToolRegistry()
    registry.register(BashTool(enabled=True))
    router = ToolRouter(
        registry,
        tmp_path,
        permission_policy=ToolPermissionPolicy(default_shell="allow"),
    )
    command = f'"{sys.executable}" -c "import time; time.sleep(2)"'

    result = asyncio.run(
        router.invoke(
            ToolCall(
                id="shell-1",
                name="Bash",
                arguments={"command": command, "timeout_s": 0.1},
                approved=True,
            )
        )
    )

    assert result.ok is False
    assert result.error == "shell command timed out after 0.1s"


def test_workspace_write_can_require_approval(tmp_path) -> None:
    registry = ToolRegistry()
    registry.register(WriteFileTool())
    router = ToolRouter(
        registry,
        tmp_path,
        permission_policy=ToolPermissionPolicy(workspace_write="ask"),
    )

    result = asyncio.run(
        router.invoke(
            ToolCall(
                id="write-1",
                name="Write",
                arguments={"path": "notes.txt", "content": "hello"},
            )
        )
    )

    assert result.ok is False
    assert result.error == "approval required"
    assert result.content["reason"] == "workspace write requires approval by policy"
    assert not (tmp_path / "notes.txt").exists()
