import asyncio

from agent_system.execution import Executor
from agent_system.models import AgentState, Plan, RunMode, Step
from agent_system.tools import ToolRegistry, ToolRouter
from agent_system.tools.builtin import EditFileTool, GlobTool, GrepSearchTool, ReadFileTool


def make_router(workspace_root) -> ToolRouter:
    registry = ToolRegistry()
    registry.register(ReadFileTool())
    registry.register(GrepSearchTool())
    registry.register(EditFileTool())
    registry.register(GlobTool())
    return ToolRouter(registry, workspace_root)


def test_executor_invokes_file_read_tool(tmp_path) -> None:
    (tmp_path / "README.md").write_text("hello agent", encoding="utf-8")
    executor = Executor(tool_router=make_router(tmp_path))
    plan = Plan(
        goal="Read file",
        mode=RunMode.ACT,
        steps=[
            Step(
                id="step-1",
                title="Read README",
                objective="Read README.md",
                suggested_tools=["Read"],
            )
        ],
    )
    state = AgentState(session_id="session-1", task_id="task-1", mode=RunMode.ACT)

    result = asyncio.run(executor.execute(plan, state))

    assert result.step_results[0].ok is True
    assert result.tool_results[0].name == "Read"
    assert result.tool_results[0].content["content"] == "hello agent"
    assert state.completed_steps == {"step-1"}


def test_executor_strips_markdown_and_cjk_punctuation_from_paths(tmp_path) -> None:
    (tmp_path / "README.md").write_text("hello punctuation", encoding="utf-8")
    executor = Executor(tool_router=make_router(tmp_path))
    plan = Plan(
        goal="Read file",
        mode=RunMode.ACT,
        steps=[
            Step(
                id="step-1",
                title="Read README",
                objective="读取 `README.md`。",
                suggested_tools=["Read"],
            )
        ],
    )
    state = AgentState(session_id="session-1", task_id="task-1", mode=RunMode.ACT)

    result = asyncio.run(executor.execute(plan, state))

    assert result.step_results[0].ok is True
    assert result.tool_results[0].content["content"] == "hello punctuation"


def test_executor_prefers_structured_tool_calls(tmp_path) -> None:
    (tmp_path / "README.md").write_text("structured call", encoding="utf-8")
    executor = Executor(tool_router=make_router(tmp_path))
    plan = Plan(
        goal="Read file",
        mode=RunMode.ACT,
        steps=[
            Step(
                id="step-1",
                title="Read README",
                objective="ignore this objective",
                suggested_tools=["Grep"],
                tool_calls=[
                    {
                        "id": "call-1",
                        "name": "Read",
                        "arguments": {"path": "README.md"},
                    }
                ],
            )
        ],
    )
    state = AgentState(session_id="session-1", task_id="task-1", mode=RunMode.ACT)

    result = asyncio.run(executor.execute(plan, state))

    assert result.step_results[0].ok is True
    assert result.tool_results[0].call_id == "call-1"
    assert result.tool_results[0].name == "Read"
    assert result.tool_results[0].content["content"] == "structured call"


def test_executor_invokes_grep_search_tool_with_key_value_arguments(tmp_path) -> None:
    (tmp_path / "README.md").write_text("alpha\nbeta\n", encoding="utf-8")
    executor = Executor(tool_router=make_router(tmp_path))
    plan = Plan(
        goal="Search file",
        mode=RunMode.ACT,
        steps=[
            Step(
                id="step-1",
                title="Search README",
                objective="pattern=alpha path=README.md",
                suggested_tools=["Grep"],
            )
        ],
    )
    state = AgentState(session_id="session-1", task_id="task-1", mode=RunMode.ACT)

    result = asyncio.run(executor.execute(plan, state))

    assert result.step_results[0].ok is True
    assert result.tool_results[0].content["count"] == 1
    assert result.tool_results[0].content["matches"][0]["line"] == "alpha"
    assert state.completed_steps == {"step-1"}


def test_executor_invokes_glob_tool_with_key_value_arguments(tmp_path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("print(1)", encoding="utf-8")
    executor = Executor(tool_router=make_router(tmp_path))
    plan = Plan(
        goal="List project files",
        mode=RunMode.ACT,
        steps=[
            Step(
                id="step-1",
                title="List files",
                objective="pattern=**/*.py path=.",
                suggested_tools=["Glob"],
            )
        ],
    )
    state = AgentState(session_id="session-1", task_id="task-1", mode=RunMode.ACT)

    result = asyncio.run(executor.execute(plan, state))

    assert result.step_results[0].ok is True
    assert result.tool_results[0].name == "Glob"
    assert result.tool_results[0].content["matches"][0]["relative_path"] == "src/app.py"


def test_executor_does_not_complete_step_when_tool_fails(tmp_path) -> None:
    executor = Executor(tool_router=make_router(tmp_path))
    plan = Plan(
        goal="Read missing file",
        mode=RunMode.ACT,
        steps=[
            Step(
                id="step-1",
                title="Read missing",
                objective="missing.txt",
                suggested_tools=["Read"],
            )
        ],
    )
    state = AgentState(session_id="session-1", task_id="task-1", mode=RunMode.ACT)

    result = asyncio.run(executor.execute(plan, state))

    assert result.step_results[0].ok is False
    assert result.tool_results[0].ok is False
    assert state.completed_steps == set()


def test_executor_does_not_mock_steps_without_executable_tools() -> None:
    executor = Executor()
    plan = Plan(
        goal="Answer question",
        mode=RunMode.ACT,
        steps=[
            Step(
                id="step-1",
                title="Answer",
                objective="Explain available capabilities",
            )
        ],
    )
    state = AgentState(session_id="session-1", task_id="task-1", mode=RunMode.ACT)

    result = asyncio.run(executor.execute(plan, state))

    assert result.step_results[0].ok is False
    assert result.step_results[0].summary == "No executable tool call for step: Answer"
    assert result.tool_results == []
    assert state.completed_steps == set()
