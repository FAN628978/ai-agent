import asyncio

from agent_system.models import RunMode, UserRequest
from agent_system.runtime import AgentRuntime, InMemoryCheckpointStore


async def collect_events(runtime: AgentRuntime, request: UserRequest) -> list[str]:
    return [event.type async for event in runtime.run(request)]


def make_request(mode: RunMode = RunMode.ACT) -> UserRequest:
    return UserRequest(
        session_id="session-1",
        user_id="user-1",
        workspace_id="workspace-1",
        content="Inspect the project",
        mode=mode,
    )


def test_runtime_completes_act_mode_event_flow() -> None:
    runtime = AgentRuntime()

    event_types = asyncio.run(collect_events(runtime, make_request()))

    assert event_types == [
        "run.started",
        "plan.created",
        "execution.completed",
        "reflection.completed",
        "run.completed",
    ]


def test_runtime_plan_mode_stops_for_approval() -> None:
    runtime = AgentRuntime()

    event_types = asyncio.run(collect_events(runtime, make_request(mode=RunMode.PLAN)))

    assert event_types == [
        "run.started",
        "plan.created",
        "run.waiting_for_approval",
    ]


async def run_with_checkpoint() -> tuple[object, object]:
    checkpoints = InMemoryCheckpointStore()
    runtime = AgentRuntime(checkpoints=checkpoints)
    events = [event async for event in runtime.run(make_request())]
    task_id = events[0].data["task_id"]
    state = await checkpoints.get(task_id)
    return events, state


def test_runtime_saves_checkpoint_state() -> None:
    _events, state = asyncio.run(run_with_checkpoint())

    assert state is not None
    assert state.plan is not None
    assert state.completed_steps == {"step-1"}
    assert len(state.tool_results) == 1
