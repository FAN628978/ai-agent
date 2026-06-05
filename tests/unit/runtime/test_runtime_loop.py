import asyncio
import json

from agent_system.execution import Executor
from agent_system.agents import AgentAction, AgentReasoner
from agent_system.llm import ChatMessage, ChatResponse
from agent_system.models import AgentEvent, Plan, RunMode, Step, ToolCall, ToolResult, UserRequest
from agent_system.observability import JsonlEventLogger
from agent_system.runtime import AgentRuntime, InMemoryCheckpointStore, InMemorySessionStore, SessionRecord
from agent_system.tools import ToolPermissionPolicy, ToolRegistry, ToolRouter
from agent_system.tools.builtin import GlobTool, ReadFileTool, WriteFileTool


async def collect_events(runtime: AgentRuntime, request: UserRequest) -> list[str]:
    return [event.type async for event in runtime.run(request)]


async def _collect_full_events(runtime: AgentRuntime, request: UserRequest) -> list[AgentEvent]:
    return [event async for event in runtime.run(request)]


def make_request(mode: RunMode = RunMode.ACT) -> UserRequest:
    return UserRequest(
        session_id="session-1",
        user_id="user-1",
        workspace_id="workspace-1",
        content="Inspect the project",
        mode=mode,
    )


class StaticPlanner:
    async def make_plan(self, request: UserRequest, session_context: str | None = None) -> Plan:
        del session_context
        return Plan(
            goal=request.content,
            mode=request.mode,
            steps=[
                Step(
                    id="step-1",
                    title="Handle request",
                    objective=request.content,
                    suggested_tools=["Glob"],
                    tool_calls=[
                        ToolCall(
                            id="step-1:Glob",
                            name="Glob",
                            arguments={"pattern": "*", "path": "."},
                        )
                    ],
                )
            ],
        )


class NoToolPlanner:
    async def make_plan(self, request: UserRequest, session_context: str | None = None) -> Plan:
        del session_context
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


class FailingPlanner:
    async def make_plan(self, request: UserRequest, session_context: str | None = None) -> Plan:
        del request, session_context
        raise ValueError("LLM planner response did not contain a JSON plan.")


class FinalAnswerReasoner:
    async def next_action(self, **kwargs) -> AgentAction:
        assert kwargs["tool_results"]
        return AgentAction(thought="Observed the workspace.", final_answer="The workspace was inspected.")


class ContinueThenAnswerReasoner:
    def __init__(self) -> None:
        self.calls = 0

    async def next_action(self, **kwargs) -> AgentAction:
        self.calls += 1
        if self.calls == 1:
            return AgentAction(
                thought="Need to read README after the initial plan.",
                tool_calls=[
                    ToolCall(
                        id="read-1",
                        name="Read",
                        arguments={"path": "README.md"},
                    )
                ],
            )
        return AgentAction(thought="README was observed.", final_answer="README says hello agent.")


class SequencedLLMClient:
    def __init__(self, contents: list[str]) -> None:
        self.contents = contents
        self.calls = 0
        self.messages_history: list[list[ChatMessage]] = []

    async def chat(
        self,
        messages: list[ChatMessage],
        *,
        max_tokens: int = 512,
        temperature: float = 0.2,
        tools: list[dict[str, object]] | None = None,
    ) -> ChatResponse:
        del tools
        self.messages_history.append(messages)
        content = self.contents[min(self.calls, len(self.contents) - 1)]
        self.calls += 1
        return ChatResponse(model="fake", content=content)


def make_runtime_with_glob(**kwargs) -> AgentRuntime:
    registry = ToolRegistry()
    registry.register(GlobTool())
    return AgentRuntime(
        planner=kwargs.pop("planner", StaticPlanner()),
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
    runtime = AgentRuntime(planner=NoToolPlanner())

    event_types = asyncio.run(collect_events(runtime, make_request()))

    assert event_types == [
        "run.started",
        "plan.created",
        "execution.completed",
        "reflection.completed",
        "run.needs_user_input",
    ]


def test_runtime_needs_user_input_when_planner_fails() -> None:
    runtime = AgentRuntime(planner=FailingPlanner())

    events = asyncio.run(_collect_full_events(runtime, make_request()))

    assert [event.type for event in events] == [
        "run.started",
        "run.needs_user_input",
    ]
    assert events[-1].data["issues"] == [
        "Planner failed to produce a valid plan: LLM planner response did not contain a JSON plan."
    ]


def test_runtime_reasoner_can_create_final_answer_after_observation() -> None:
    runtime = make_runtime_with_glob(reasoner=FinalAnswerReasoner())

    events = asyncio.run(_collect_full_events(runtime, make_request()))

    assert [event.type for event in events] == [
        "run.started",
        "plan.created",
        "execution.completed",
        "reasoning.completed",
        "answer.created",
        "run.completed",
    ]
    assert events[-2].data["content"] == "The workspace was inspected."


def test_runtime_reasoner_can_continue_with_more_tool_calls(tmp_path) -> None:
    (tmp_path / "README.md").write_text("hello agent", encoding="utf-8")
    registry = ToolRegistry()
    registry.register(ReadFileTool())
    reasoner = ContinueThenAnswerReasoner()
    runtime = AgentRuntime(
        planner=NoToolPlanner(),
        executor=Executor(ToolRouter(registry, tmp_path)),
        reasoner=reasoner,
    )

    events = asyncio.run(_collect_full_events(runtime, make_request()))

    assert [event.type for event in events] == [
        "run.started",
        "plan.created",
        "execution.completed",
        "reasoning.completed",
        "plan.created",
        "execution.completed",
        "reasoning.completed",
        "answer.created",
        "run.completed",
    ]
    assert reasoner.calls == 2
    assert events[-2].data["content"] == "README says hello agent."


def test_runtime_returns_unknown_tool_observation_and_reasoner_recovers(tmp_path) -> None:
    (tmp_path / "notes.txt").write_text("hello from notes", encoding="utf-8")
    registry = ToolRegistry()
    registry.register(GlobTool())
    client = SequencedLLMClient(
        [
            """
            {
              "thought": "Try an unavailable directory tool.",
              "tool_calls": [{"id": "bad-1", "name": "DirectoryInspector", "arguments": {}}],
              "final_answer": null,
              "needs_user_input": []
            }
            """,
            """
            {
              "thought": "Use a registered tool from the observation.",
              "tool_calls": [{"id": "glob-1", "name": "Glob", "arguments": {"pattern": "*", "path": "."}}],
              "final_answer": null,
              "needs_user_input": []
            }
            """,
            """
            {
              "thought": "The directory listing is enough.",
              "tool_calls": [],
              "final_answer": "The directory contains notes.txt.",
              "needs_user_input": []
            }
            """,
        ]
    )
    reasoner = AgentReasoner(client, tools=registry.schemas())
    runtime = AgentRuntime(
        planner=NoToolPlanner(),
        executor=Executor(ToolRouter(registry, tmp_path)),
        reasoner=reasoner,
    )

    events = asyncio.run(_collect_full_events(runtime, make_request()))
    tool_results = [
        result
        for event in events
        if event.type == "execution.completed"
        for result in event.data.get("tool_results", [])
    ]

    assert events[-2].type == "answer.created"
    assert events[-2].data["content"] == "The directory contains notes.txt."
    assert tool_results[0]["error"] == "unknown tool: DirectoryInspector"
    assert tool_results[0]["content"]["available_tools"] == ["Glob"]
    assert "unknown tool: DirectoryInspector" in client.messages_history[1][-1].content
    assert "available_tools" in client.messages_history[1][-1].content


def test_runtime_returns_validation_observation_and_reasoner_recovers(tmp_path) -> None:
    (tmp_path / "notes.txt").write_text("hello from notes", encoding="utf-8")
    registry = ToolRegistry()
    registry.register(ReadFileTool())
    client = SequencedLLMClient(
        [
            """
            {
              "thought": "Try reading without a path.",
              "tool_calls": [{"id": "read-bad", "name": "Read", "arguments": {}}],
              "final_answer": null,
              "needs_user_input": []
            }
            """,
            """
            {
              "thought": "Fix the missing path argument from the observation.",
              "tool_calls": [{"id": "read-ok", "name": "Read", "arguments": {"path": "notes.txt"}}],
              "final_answer": null,
              "needs_user_input": []
            }
            """,
            """
            {
              "thought": "The file was read.",
              "tool_calls": [],
              "final_answer": "notes.txt says hello from notes.",
              "needs_user_input": []
            }
            """,
        ]
    )
    reasoner = AgentReasoner(client, tools=registry.schemas())
    runtime = AgentRuntime(
        planner=NoToolPlanner(),
        executor=Executor(ToolRouter(registry, tmp_path)),
        reasoner=reasoner,
    )

    events = asyncio.run(_collect_full_events(runtime, make_request()))
    tool_results = [
        result
        for event in events
        if event.type == "execution.completed"
        for result in event.data.get("tool_results", [])
    ]

    assert events[-2].data["content"] == "notes.txt says hello from notes."
    assert tool_results[0]["error"] == "missing required argument: path"
    assert tool_results[0]["content"]["required_args"] == ["path"]
    assert tool_results[0]["content"]["available_tools"] == ["Read"]
    assert tool_results[1]["ok"] is True
    assert "missing required argument: path" in client.messages_history[1][-1].content
    assert "required_args" in client.messages_history[1][-1].content
    assert "available_tools" in client.messages_history[1][-1].content


def test_runtime_reasoner_can_run_multiple_tool_steps(tmp_path) -> None:
    (tmp_path / "notes.txt").write_text("alpha detail", encoding="utf-8")
    registry = ToolRegistry()
    registry.register(GlobTool())
    registry.register(ReadFileTool())
    client = SequencedLLMClient(
        [
            """
            {
              "thought": "Discover files first.",
              "tool_calls": [{"id": "glob-1", "name": "Glob", "arguments": {"pattern": "*.txt", "path": "."}}],
              "final_answer": null,
              "needs_user_input": []
            }
            """,
            """
            {
              "thought": "Read the discovered file.",
              "tool_calls": [{"id": "read-1", "name": "Read", "arguments": {"path": "notes.txt"}}],
              "final_answer": null,
              "needs_user_input": []
            }
            """,
            """
            {
              "thought": "Answer from the read result.",
              "tool_calls": [],
              "final_answer": "The notes file contains alpha detail.",
              "needs_user_input": []
            }
            """,
        ]
    )
    reasoner = AgentReasoner(client, tools=registry.schemas())
    runtime = AgentRuntime(
        planner=NoToolPlanner(),
        executor=Executor(ToolRouter(registry, tmp_path)),
        reasoner=reasoner,
    )

    events = asyncio.run(_collect_full_events(runtime, make_request()))
    executed_tool_names = [
        result["name"]
        for event in events
        if event.type == "execution.completed"
        for result in event.data.get("tool_results", [])
    ]

    assert executed_tool_names == ["Glob", "Read"]
    assert events[-2].data["content"] == "The notes file contains alpha detail."


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
    runtime = AgentRuntime(planner=NoToolPlanner())

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


class WriteApprovalPlanner:
    async def make_plan(self, request: UserRequest, session_context: str | None = None) -> Plan:
        del session_context
        return Plan(
            goal=request.content,
            mode=request.mode,
            steps=[
                Step(
                    id="step-1",
                    title="Write notes",
                    objective="Write notes.txt",
                    tool_calls=[
                        ToolCall(
                            id="write-1",
                            name="Write",
                            arguments={"path": "notes.txt", "content": "hello"},
                        )
                    ],
                )
            ],
        )


def test_runtime_emits_tool_approval_event(tmp_path) -> None:
    registry = ToolRegistry()
    registry.register(WriteFileTool())
    router = ToolRouter(
        registry,
        tmp_path,
        permission_policy=ToolPermissionPolicy(workspace_write="ask"),
    )
    runtime = AgentRuntime(
        planner=WriteApprovalPlanner(),
        executor=Executor(router),
    )

    events = asyncio.run(_collect_full_events(runtime, make_request()))

    assert [event.type for event in events] == [
        "run.started",
        "plan.created",
        "execution.completed",
        "run.waiting_for_tool_approval",
    ]
    approval_event = events[-1]
    assert approval_event.data["tool_approvals"] == [
        {
            "call_id": "write-1",
            "tool": "Write",
            "reason": "workspace write requires approval by policy",
            "arguments_summary": {"path": "notes.txt", "content": "hello"},
        }
    ]
    assert not (tmp_path / "notes.txt").exists()


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


def test_session_context_summary_preserves_glob_match_paths() -> None:
    session = SessionRecord(
        session_id="session-1",
        summary="User asked to inspect the project.",
        recent_tool_results=[
            ToolResult(
                call_id="call-1",
                name="Glob",
                ok=True,
                content={
                    "path": ".",
                    "pattern": "*",
                    "count": 4,
                    "matches": [
                        {"relative_path": "README.md", "type": "file"},
                        {"relative_path": "pyproject.toml", "type": "file"},
                        {"relative_path": "src/agent_system/api/cli.py", "type": "file"},
                        {"relative_path": "tests/unit/api/test_cli.py", "type": "file"},
                    ],
                },
            )
        ],
    )

    context = session.context_summary(max_chars=1200)

    assert "Recent tool results:" in context
    assert "README.md" in context
    assert "pyproject.toml" in context
    assert "src/agent_system/api/cli.py" in context
    assert "tests/unit/api/test_cli.py" in context
