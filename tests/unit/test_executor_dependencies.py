import asyncio

from agent_system.execution import Executor
from agent_system.models import AgentState, Plan, RunMode, Step, ToolCall
from agent_system.tools import ToolRegistry, ToolRouter
from agent_system.tools.builtin import GlobTool, GrepSearchTool, ReadFileTool


def make_state() -> AgentState:
    return AgentState(session_id="session-1", task_id="task-1", mode=RunMode.ACT)


def make_router(workspace_root) -> ToolRouter:
    registry = ToolRegistry()
    registry.register(ReadFileTool())
    registry.register(GrepSearchTool())
    registry.register(GlobTool())
    return ToolRouter(registry, workspace_root)


def make_plan(steps: list[Step]) -> Plan:
    return Plan(goal="Test dependencies", mode=RunMode.ACT, steps=steps)


def test_executor_sorts_steps_by_depends_on(tmp_path) -> None:
    (tmp_path / "README.md").write_text("hello", encoding="utf-8")
    executor = Executor(make_router(tmp_path))
    plan = make_plan(
        [
            Step(
                id="step-2",
                title="Read README",
                objective="README.md",
                depends_on=["step-1"],
                suggested_tools=["Read"],
            ),
            Step(
                id="step-1",
                title="List files",
                objective="pattern=* path=.",
                suggested_tools=["Glob"],
            ),
        ]
    )
    state = make_state()

    result = asyncio.run(executor.execute(plan, state))

    assert [step.step_id for step in result.step_results] == ["step-1", "step-2"]
    assert [tool.name for tool in result.tool_results] == ["Glob", "Read"]
    assert [step.status for step in result.step_results] == ["success", "success"]
    assert state.completed_steps == {"step-1", "step-2"}


def test_executor_blocks_step_with_missing_dependency(tmp_path) -> None:
    executor = Executor(make_router(tmp_path))
    plan = make_plan(
        [
            Step(
                id="step-1",
                title="Read README",
                objective="README.md",
                depends_on=["missing-step"],
                suggested_tools=["Read"],
            )
        ]
    )

    result = asyncio.run(executor.execute(plan, make_state()))

    assert result.step_results[0].ok is False
    assert result.step_results[0].status == "blocked"
    assert result.step_results[0].error_type == "dependency_missing"
    assert "missing-step" in result.step_results[0].summary
    assert result.tool_results == []


def test_executor_blocks_steps_in_dependency_cycle(tmp_path) -> None:
    executor = Executor(make_router(tmp_path))
    plan = make_plan(
        [
            Step(
                id="step-1",
                title="First",
                objective="README.md",
                depends_on=["step-2"],
                suggested_tools=["Read"],
            ),
            Step(
                id="step-2",
                title="Second",
                objective="README.md",
                depends_on=["step-1"],
                suggested_tools=["Read"],
            ),
        ]
    )

    result = asyncio.run(executor.execute(plan, make_state()))

    assert [step.status for step in result.step_results] == ["blocked", "blocked"]
    assert [step.error_type for step in result.step_results] == ["dependency_cycle", "dependency_cycle"]
    assert result.tool_results == []


def test_executor_blocks_downstream_step_when_dependency_fails(tmp_path) -> None:
    (tmp_path / "README.md").write_text("hello", encoding="utf-8")
    executor = Executor(make_router(tmp_path))
    plan = make_plan(
        [
            Step(
                id="step-1",
                title="Read missing",
                objective="missing.txt",
                suggested_tools=["Read"],
            ),
            Step(
                id="step-2",
                title="Read README",
                objective="README.md",
                depends_on=["step-1"],
                suggested_tools=["Read"],
            ),
        ]
    )
    state = make_state()

    result = asyncio.run(executor.execute(plan, state))

    assert result.step_results[0].status == "failed"
    assert result.step_results[0].error_type == "tool_runtime_error"
    assert result.step_results[1].status == "blocked"
    assert result.step_results[1].error_type == "dependency_failed"
    assert [tool.name for tool in result.tool_results] == ["Read"]
    assert state.completed_steps == set()


def test_executor_marks_step_without_executable_tool(tmp_path) -> None:
    executor = Executor(make_router(tmp_path))
    plan = make_plan(
        [
            Step(
                id="step-1",
                title="Explain",
                objective="Explain capabilities",
            )
        ]
    )

    result = asyncio.run(executor.execute(plan, make_state()))

    assert result.step_results[0].ok is False
    assert result.step_results[0].status == "failed"
    assert result.step_results[0].error_type == "no_executable_tool"
    assert result.tool_results == []


def test_executor_classifies_unknown_tool(tmp_path) -> None:
    executor = Executor(make_router(tmp_path))
    plan = make_plan(
        [
            Step(
                id="step-1",
                title="Use missing tool",
                objective="Use missing tool",
                tool_calls=[ToolCall(id="missing-1", name="Missing", arguments={})],
            )
        ]
    )

    result = asyncio.run(executor.execute(plan, make_state()))

    assert result.step_results[0].ok is False
    assert result.step_results[0].status == "failed"
    assert result.step_results[0].error_type == "unknown_tool"
    assert result.tool_results[0].error == "unknown tool: Missing"


def test_executor_classifies_validation_failed(tmp_path) -> None:
    executor = Executor(make_router(tmp_path))
    plan = make_plan(
        [
            Step(
                id="step-1",
                title="Read without path",
                objective="Read without path",
                tool_calls=[ToolCall(id="read-1", name="Read", arguments={})],
            )
        ]
    )

    result = asyncio.run(executor.execute(plan, make_state()))

    assert result.step_results[0].ok is False
    assert result.step_results[0].status == "failed"
    assert result.step_results[0].error_type == "validation_failed"
    assert result.tool_results[0].metadata["audit"]["status"] == "validation_failed"


def test_execution_summary_keeps_existing_fields(tmp_path) -> None:
    (tmp_path / "README.md").write_text("hello", encoding="utf-8")
    executor = Executor(make_router(tmp_path))
    plan = make_plan(
        [
            Step(id="step-1", title="Read README", objective="README.md", suggested_tools=["Read"]),
            Step(id="step-2", title="No tool", objective="No tool"),
        ]
    )

    result = asyncio.run(executor.execute(plan, make_state()))
    summary = result.summary()

    assert summary["completed_steps"] == ["step-1"]
    assert summary["failed_steps"] == ["step-2"]
    assert summary["tool_result_count"] == 1
    assert summary["blocked_steps"] == []
    assert summary["waiting_steps"] == []
    assert summary["error_types"] == ["no_executable_tool"]
