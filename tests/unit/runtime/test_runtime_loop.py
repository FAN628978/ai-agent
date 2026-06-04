import asyncio
import json

from agent_system.execution import Executor
from agent_system.models import Plan, RunMode, Step, ToolResult, UserRequest
from agent_system.observability import JsonlEventLogger
from agent_system.runtime import AgentRuntime, InMemoryCheckpointStore, InMemorySessionStore, SessionRecord
from agent_system.tools import ToolRegistry, ToolRouter
from agent_system.tools.builtin import GlobTool


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


def make_runtime_with_glob(**kwargs) -> AgentRuntime:
    registry = ToolRegistry()
    registry.register(GlobTool())
    return AgentRuntime(
        executor=Executor(ToolRouter(registry, ".")),
        **kwargs,
    )


def test_runtime_completes_act_mode_event_flow() -> None:
    runtime = make_runtime_with_glob()

    event_types = asyncio.run(collect_events(runtime, make_request()))

    assert event_types == [
        "run.started",
        "plan.created",
        "execution.completed",
        "reflection.completed",
        "run.completed",
    ]


def test_runtime_needs_user_input_when_no_real_tool_can_run() -> None:
    runtime = AgentRuntime()

    event_types = asyncio.run(collect_events(runtime, make_request()))

    assert event_types == [
        "run.started",
        "plan.created",
        "execution.completed",
        "reflection.completed",
        "run.needs_user_input",
    ]


def test_runtime_logs_event_flow_to_jsonl(tmp_path) -> None:
    path = tmp_path / "events.jsonl"
    runtime = make_runtime_with_glob(event_logger=JsonlEventLogger(path))

    event_types = asyncio.run(collect_events(runtime, make_request()))
    records = [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]

    assert [record["event_type"] for record in records] == event_types
    assert {record["session_id"] for record in records} == {"session-1"}
    assert {record["task_id"] for record in records} == {records[0]["task_id"]}
    plan_record = next(record for record in records if record["event_type"] == "plan.created")
    assert plan_record["data"]["goal"] == "Inspect the project"
    assert plan_record["data"]["step_count"] == 1
    execution_record = next(record for record in records if record["event_type"] == "execution.completed")
    assert "tool_results" not in execution_record["data"]


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
    runtime = make_runtime_with_glob(checkpoints=checkpoints)
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


def test_runtime_saves_session_state_across_turns() -> None:
    sessions = InMemorySessionStore()
    runtime = make_runtime_with_glob(session_store=sessions)

    asyncio.run(collect_events(runtime, make_request()))
    session = asyncio.run(sessions.get("session-1"))

    assert session.recent_plan is not None
    assert session.recent_plan.goal == "Inspect the project"
    assert [event.type for event in session.recent_events] == [
        "run.started",
        "plan.created",
        "execution.completed",
        "reflection.completed",
        "run.completed",
    ]
    assert len(session.recent_tool_results) == 1
    assert "Inspect the project" in session.summary


def test_runtime_keeps_sessions_isolated() -> None:
    sessions = InMemorySessionStore()
    runtime = make_runtime_with_glob(session_store=sessions)
    first = make_request()
    second = UserRequest(
        session_id="session-2",
        user_id="user-1",
        workspace_id="workspace-1",
        content="Inspect another workspace",
    )

    asyncio.run(collect_events(runtime, first))
    asyncio.run(collect_events(runtime, second))

    first_session = asyncio.run(sessions.get("session-1"))
    second_session = asyncio.run(sessions.get("session-2"))

    assert first_session.recent_plan is not None
    assert second_session.recent_plan is not None
    assert first_session.recent_plan.goal == "Inspect the project"
    assert second_session.recent_plan.goal == "Inspect another workspace"


class RecordingPlanner:
    def __init__(self) -> None:
        self.session_contexts: list[str | None] = []

    async def make_plan(self, request: UserRequest, session_context: str | None = None) -> Plan:
        self.session_contexts.append(session_context)
        return Plan(
            goal=request.content,
            mode=request.mode,
            steps=[
                Step(
                    id="step-1",
                    title="Handle request",
                    objective=request.content,
                )
            ],
        )


def test_runtime_passes_previous_session_context_to_planner() -> None:
    planner = RecordingPlanner()
    runtime = make_runtime_with_glob(planner=planner)

    asyncio.run(collect_events(runtime, make_request()))
    second = make_request()
    second.content = "Continue from previous result"
    asyncio.run(collect_events(runtime, second))

    assert planner.session_contexts[0] == ""
    assert planner.session_contexts[1] is not None
    assert "Conversation summary:" in planner.session_contexts[1]
    assert "Previous plan goal: Inspect the project" in planner.session_contexts[1]


def test_session_context_summary_limits_tool_result_content() -> None:
    session = SessionRecord(
        session_id="session-1",
        summary="Previous user question",
        recent_tool_results=[
            ToolResult(
                call_id="call-1",
                name="Read",
                ok=True,
                content={"path": "README.md", "content": "x" * 1000},
            )
        ],
    )

    context = session.context_summary(max_chars=800)

    assert "Recent tool results:" in context
    assert "Read call_id=call-1 status=ok" in context
    assert "x" * 1000 not in context
    assert len(context) <= 814
