import pytest
from pydantic import ValidationError

from agent_system.models import (
    AgentEvent,
    AgentState,
    Critique,
    Plan,
    RunMode,
    Step,
    ToolCall,
    ToolResult,
    UserRequest,
)


def test_user_request_defaults_and_serialization() -> None:
    request = UserRequest(
        session_id="session-1",
        user_id="user-1",
        workspace_id="workspace-1",
        content="read the project",
    )

    assert request.mode == RunMode.ACT
    assert request.attachments == []
    assert request.metadata == {}
    assert request.model_dump(mode="json")["mode"] == "act"


def test_plan_step_and_critique_defaults() -> None:
    step = Step(id="step-1", title="Inspect", objective="Read project files")
    plan = Plan(goal="Understand project", mode=RunMode.PLAN, steps=[step])
    critique = Critique(done=True, confidence=0.9)

    assert step.depends_on == []
    assert step.suggested_tools == []
    assert step.tool_calls == []
    assert step.risk == "low"
    assert plan.assumptions == []
    assert plan.risks == []
    assert plan.goal == "Understand project"
    assert plan.task_goal == "Understand project"
    assert plan.expected_outputs == []
    assert plan.constraints == []
    assert plan.success_criteria == []
    assert critique.issues == []
    assert critique.next_action == "finish"
    assert critique.reason == ""
    assert critique.missing_items == []
    assert critique.suggested_next_action == ""


def test_step_tool_calls_roundtrip() -> None:
    step = Step(
        id="step-1",
        title="Read",
        objective="Read README",
        tool_calls=[
            ToolCall(
                id="call-1",
                name="Read",
                arguments={"path": "README.md"},
            )
        ],
    )

    dumped = step.model_dump(mode="json")
    loaded = Step.model_validate(dumped)

    assert dumped["tool_calls"][0]["name"] == "Read"
    assert loaded.tool_calls[0].arguments == {"path": "README.md"}


def test_tool_call_and_result_defaults() -> None:
    call = ToolCall(id="call-1", name="Read", arguments={"path": "README.md"})
    result = ToolResult(
        call_id=call.id,
        name=call.name,
        ok=True,
        content={"text": "ok"},
    )

    assert call.timeout_s == 30
    assert call.requires_approval is False
    assert result.error is None
    assert result.metadata == {}


def test_agent_state_defaults_and_json_roundtrip() -> None:
    state = AgentState(session_id="session-1", task_id="task-1", mode=RunMode.ACT)
    state.completed_steps.add("step-1")

    dumped = state.model_dump(mode="json")
    loaded = AgentState.model_validate(dumped)

    assert dumped["mode"] == "act"
    assert dumped["completed_steps"] == ["step-1"]
    assert loaded.completed_steps == {"step-1"}
    assert loaded.step_results == []
    assert loaded.iteration == 0
    assert loaded.max_iterations == 20


def test_agent_event_defaults() -> None:
    event = AgentEvent(type="run.started")

    assert event.data == {}
    assert event.model_dump() == {"type": "run.started", "data": {}}


def test_invalid_enum_values_raise_validation_error() -> None:
    with pytest.raises(ValidationError):
        UserRequest.model_validate(
            {
                "session_id": "session-1",
                "user_id": "user-1",
                "workspace_id": "workspace-1",
                "content": "hello",
                "mode": "invalid",
            }
        )
