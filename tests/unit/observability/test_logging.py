import json

from agent_system.models import AgentEvent, RunMode, UserRequest
from agent_system.observability import JsonlEventLogger


def make_request() -> UserRequest:
    return UserRequest(
        session_id="session-1",
        user_id="user-1",
        workspace_id="workspace-1",
        content="Inspect the project",
        mode=RunMode.ACT,
    )


def test_jsonl_event_logger_writes_event_record(tmp_path) -> None:
    path = tmp_path / "nested" / "events.jsonl"
    logger = JsonlEventLogger(path=path, level="info")

    logger.log_event(
        AgentEvent(type="run.started", data={"task_id": "task-1"}),
        make_request(),
    )

    record = json.loads(path.read_text(encoding="utf-8"))
    assert record["level"] == "info"
    assert record["event_type"] == "run.started"
    assert record["session_id"] == "session-1"
    assert record["task_id"] == "task-1"
    assert record["user_id"] == "user-1"
    assert record["workspace_id"] == "workspace-1"
    assert record["timestamp"].endswith("Z")


def test_jsonl_event_logger_summarizes_plan_created(tmp_path) -> None:
    path = tmp_path / "events.jsonl"
    logger = JsonlEventLogger(path=path)

    logger.log_event(
        AgentEvent(
            type="plan.created",
            data={
                "goal": "Inspect project",
                "mode": "act",
                "steps": [{"id": "step-1", "objective": "large payload"}],
                "risks": ["risk"],
            },
        ),
        make_request(),
        task_id="task-1",
    )

    record = json.loads(path.read_text(encoding="utf-8"))
    assert record["task_id"] == "task-1"
    assert record["data"] == {
        "goal": "Inspect project",
        "task_goal": "Inspect project",
        "mode": "act",
        "step_count": 1,
        "risk_count": 1,
    }


def test_jsonl_event_logger_removes_tool_results_from_execution_summary(tmp_path) -> None:
    path = tmp_path / "events.jsonl"
    logger = JsonlEventLogger(path=path)

    logger.log_event(
        AgentEvent(
            type="execution.completed",
            data={
                "completed_steps": ["step-1"],
                "failed_steps": [],
                "tool_result_count": 1,
                "tool_results": [{"content": "do not log"}],
            },
        ),
        make_request(),
    )

    record = json.loads(path.read_text(encoding="utf-8"))
    assert record["data"] == {
        "completed_steps": ["step-1"],
        "failed_steps": [],
        "tool_result_count": 1,
    }
