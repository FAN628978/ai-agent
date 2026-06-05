import asyncio

from agent_system.execution import Executor
from agent_system.models import Plan, RunMode, Step, ToolCall, UserRequest
from agent_system.runtime import AgentRuntime, InMemoryCheckpointStore
from agent_system.tools import ToolRegistry, ToolRouter
from agent_system.tools.builtin import GlobTool


class StaticPlanner:
    async def make_plan(self, request: UserRequest, session_context: str | None = None) -> Plan:
        del session_context
        return Plan(
            goal=request.content,
            mode=request.mode,
            steps=[
                Step(
                    id="step-1",
                    title="List files",
                    objective="List files",
                    tool_calls=[ToolCall(id="glob-1", name="Glob", arguments={"pattern": "*", "path": "."})],
                )
            ],
        )


def make_request() -> UserRequest:
    return UserRequest(
        session_id="session-1",
        user_id="user-1",
        workspace_id="workspace-1",
        content="Inspect workspace",
        mode=RunMode.ACT,
    )


async def collect_events(runtime: AgentRuntime, request: UserRequest) -> list[object]:
    return [event async for event in runtime.run(request)]


def test_runtime_records_execution_step_results_in_state(tmp_path) -> None:
    registry = ToolRegistry()
    registry.register(GlobTool())
    checkpoints = InMemoryCheckpointStore()
    runtime = AgentRuntime(
        planner=StaticPlanner(),
        executor=Executor(ToolRouter(registry, tmp_path)),
        checkpoints=checkpoints,
    )

    events = asyncio.run(collect_events(runtime, make_request()))
    task_id = events[0].data["task_id"]
    state = asyncio.run(checkpoints.get(task_id))

    assert state is not None
    assert len(state.step_results) == 1
    assert state.step_results[0].step_id == "step-1"
    assert state.step_results[0].ok is True
    assert state.step_results[0].status == "success"
    assert state.step_results[0].error_type is None
