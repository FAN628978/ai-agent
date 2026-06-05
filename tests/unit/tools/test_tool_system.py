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


def test_registry_exports_context_and_llm_tool_definitions() -> None:
    registry = ToolRegistry()
    registry.register(ReadFileTool())

    definition = registry.definitions()[0]
    llm_tool = registry.llm_tools()[0]

    assert definition["name"] == "Read"
    assert definition["description"] == ReadFileTool().schema.description
    assert definition["risk"] == "low"
    assert definition["permission"]["filesystem"] == "read"
    assert definition["input_schema"]["required"] == ["path"]
    assert definition["required_arguments"] == ["path"]
    assert definition["optional_arguments"] == ["max_bytes"]
    assert llm_tool["type"] == "function"
    assert llm_tool["function"]["name"] == "Read"
    assert llm_tool["function"]["parameters"] == definition["input_schema"]
    assert "required_arguments" in llm_tool["function"]["description"]


def test_router_returns_error_for_unknown_tool(tmp_path) -> None:
    registry = ToolRegistry()
    registry.register(GlobTool())
    registry.register(ReadFileTool())
    router = ToolRouter(registry, tmp_path)
    call = ToolCall(id="call-1", name="missing.tool", arguments={})

    result = asyncio.run(router.invoke(call))

    assert result.ok is False
    assert result.error == "unknown tool: missing.tool"
    assert result.content["tool"] == "missing.tool"
    assert result.content["available_tools"] == ["Glob", "Read"]
    assert result.content["tool_definitions"][0]["name"] == "Glob"
    assert "description" in result.content["tool_definitions"][0]
    assert "permission" in result.content["tool_definitions"][0]
    assert "input_schema" in result.content["tool_definitions"][0]
    assert "required_arguments" in result.content["tool_definitions"][0]
    assert "optional_arguments" in result.content["tool_definitions"][0]
    assert "Choose one of the available tools" in result.content["hint"]


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


def test_router_returns_unknown_for_dirlist_alias(tmp_path) -> None:
    registry = ToolRegistry()
    registry.register(GlobTool())
    router = ToolRouter(registry, tmp_path)

    result = asyncio.run(
        router.invoke(
            ToolCall(
                id="dir-1",
                name="DirList",
                arguments={},
            )
        )
    )

    assert result.ok is False
    assert result.error == "unknown tool: DirList"
    assert result.name == "DirList"
    assert result.content["available_tools"] == ["Glob"]


def test_router_returns_unknown_for_file_listing_alias(tmp_path) -> None:
    registry = ToolRegistry()
    registry.register(GlobTool())
    router = ToolRouter(registry, tmp_path)

    result = asyncio.run(
        router.invoke(
            ToolCall(
                id="list-files-1",
                name="ListFiles",
                arguments={"path": "."},
            )
        )
    )

    assert result.ok is False
    assert result.error == "unknown tool: ListFiles"
    assert result.name == "ListFiles"
    assert result.content["available_tools"] == ["Glob"]


def test_glob_tool_can_list_absolute_path_under_read_root(tmp_path, monkeypatch) -> None:
    readable = tmp_path / "readable"
    workspace = tmp_path / "workspace"
    readable.mkdir()
    workspace.mkdir()
    (readable / "note.txt").write_text("readable note", encoding="utf-8")
    monkeypatch.setattr("agent_system.tools.base.Path.home", lambda: tmp_path)
    registry = ToolRegistry()
    registry.register(GlobTool())
    router = ToolRouter(registry, workspace)

    result = asyncio.run(
        router.invoke(
            ToolCall(
                id="glob-absolute-1",
                name="Glob",
                arguments={"path": str(readable)},
            )
        )
    )

    assert result.ok is True
    assert result.name == "Glob"
    assert result.content["path"] == str(readable)
    assert result.content["matches"][0]["relative_path"] == "note.txt"


def test_router_normalizes_file_path_argument_alias(tmp_path) -> None:
    (tmp_path / "README.md").write_text("hello", encoding="utf-8")
    registry = ToolRegistry()
    registry.register(ReadFileTool())
    router = ToolRouter(registry, tmp_path)

    result = asyncio.run(
        router.invoke(
            ToolCall(
                id="read-1",
                name="Read",
                arguments={"file_path": "README.md"},
            )
        )
    )

    assert result.ok is True
    assert result.content["content"] == "hello"


def test_read_tool_can_read_absolute_path_under_read_root(tmp_path, monkeypatch) -> None:
    readable = tmp_path / "readable.txt"
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    readable.write_text("from read root", encoding="utf-8")
    monkeypatch.setattr("agent_system.tools.base.Path.home", lambda: tmp_path)
    registry = ToolRegistry()
    registry.register(ReadFileTool())
    router = ToolRouter(registry, workspace)

    result = asyncio.run(
        router.invoke(
            ToolCall(
                id="read-absolute-1",
                name="Read",
                arguments={"path": str(readable)},
            )
        )
    )

    assert result.ok is True
    assert result.content["content"] == "from read root"


def test_router_returns_validation_error_for_missing_required_argument(tmp_path) -> None:
    registry = ToolRegistry()
    registry.register(ReadFileTool())
    router = ToolRouter(registry, tmp_path)

    result = asyncio.run(
        router.invoke(
            ToolCall(
                id="read-1",
                name="Read",
                arguments={},
            )
        )
    )

    assert result.ok is False
    assert result.error == "missing required argument: path"
    assert result.content["tool"] == "Read"
    assert result.content["required_args"] == ["path"]
    assert result.content["optional_args"] == ["max_bytes"]
    assert result.content["schema"]["properties"]["path"]["type"] == "string"
    assert result.content["tool_definition"]["input_schema"]["required"] == ["path"]
    assert result.content["available_tools"] == ["Read"]
    assert result.content["tool_definitions"][0]["name"] == "Read"
    assert "Revise the tool call" in result.content["hint"]
    assert result.metadata["audit"]["status"] == "validation_failed"


def test_shell_run_tool_executes_by_default(tmp_path) -> None:
    registry = ToolRegistry()
    registry.register(BashTool())
    router = ToolRouter(registry, tmp_path)
    command = f'"{sys.executable}" -c "print(123)"'

    result = asyncio.run(
        router.invoke(
            ToolCall(
                id="shell-1",
                name="Bash",
                arguments={"command": command},
            )
        )
    )

    assert result.ok is True
    assert result.content["returncode"] == 0
    assert result.content["stdout"].strip() == "123"
    assert result.metadata["audit"]["status"] == "success"


def test_shell_run_tool_does_not_require_approval_when_enabled(tmp_path) -> None:
    registry = ToolRegistry()
    registry.register(BashTool(enabled=True))
    router = ToolRouter(
        registry,
        tmp_path,
        permission_policy=ToolPermissionPolicy(default_shell="allow"),
    )
    command = f'"{sys.executable}" -c "print(456)"'

    result = asyncio.run(
        router.invoke(
            ToolCall(
                id="shell-1",
                name="Bash",
                arguments={"command": command},
            )
        )
    )

    assert result.ok is True
    assert result.content["returncode"] == 0
    assert result.content["stdout"].strip() == "456"
    assert result.metadata["audit"]["status"] == "success"


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
            )
        )
    )

    assert result.ok is True
    assert result.content["returncode"] == 0
    assert result.content["stdout"].strip() == "123"
    assert result.metadata["audit"]["status"] == "success"


def test_shell_run_tool_denies_destructive_command_by_policy(tmp_path) -> None:
    registry = ToolRegistry()
    registry.register(BashTool(enabled=True))
    router = ToolRouter(
        registry,
        tmp_path,
        permission_policy=ToolPermissionPolicy(default_shell="allow", destructive_commands="deny"),
    )

    result = asyncio.run(
        router.invoke(
            ToolCall(
                id="shell-1",
                name="Bash",
                arguments={"command": "git reset --hard"},
                approved=True,
            )
        )
    )

    assert result.ok is False
    assert result.error == "destructive shell command is denied by policy"
    assert result.metadata["audit"]["status"] == "denied"


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
