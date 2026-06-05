import json
from types import SimpleNamespace

from typer.testing import CliRunner

from agent_system.api.cli import (
    _render_runtime_answer,
    _strip_reasoning_blocks,
    app,
)
from agent_system.models import AgentEvent
from agent_system.tools.schemas import ToolSchema


runner = CliRunner()


class FakeRuntime:
    def __init__(self, events: list[AgentEvent] | None = None) -> None:
        self.events = events or [
            AgentEvent(type="run.started", data={"task_id": "task-1"}),
            AgentEvent(type="plan.created", data={"goal": "Inspect project"}),
            AgentEvent(type="run.completed", data={"task_id": "task-1", "confidence": 1.0}),
        ]
        self.contents: list[str] = []
        self.planner = SimpleNamespace(context=SimpleNamespace(tools=[]))

    async def run(self, request):
        self.contents.append(request.content)
        for event in self.events:
            yield event


def test_cli_plan_outputs_plan_events(monkeypatch) -> None:
    runtime = FakeRuntime(
        [
            AgentEvent(type="run.started", data={"task_id": "task-1"}),
            AgentEvent(type="plan.created", data={"goal": "Inspect project"}),
            AgentEvent(type="run.waiting_for_approval", data={"task_id": "task-1"}),
        ]
    )

    monkeypatch.setattr("agent_system.api.cli.create_runtime_from_config", lambda *args, **kwargs: runtime)

    result = runner.invoke(app, ["plan", "Inspect project", "--json"])

    assert result.exit_code == 0
    events = [json.loads(line) for line in result.output.strip().splitlines()]
    assert [event["type"] for event in events] == [
        "run.started",
        "plan.created",
        "run.waiting_for_approval",
    ]
    assert events[1]["data"]["goal"] == "Inspect project"


def test_cli_run_outputs_runtime_events(monkeypatch) -> None:
    runtime = FakeRuntime(
        [
            AgentEvent(type="run.started", data={"task_id": "task-1"}),
            AgentEvent(type="plan.created", data={"goal": "Inspect project"}),
            AgentEvent(type="execution.completed", data={"tool_result_count": 0, "tool_results": []}),
            AgentEvent(type="reflection.completed", data={"done": True}),
            AgentEvent(type="run.completed", data={"task_id": "task-1", "confidence": 1.0}),
        ]
    )

    monkeypatch.setattr("agent_system.api.cli.create_runtime_from_config", lambda *args, **kwargs: runtime)

    result = runner.invoke(app, ["run", "Inspect project", "--json"])

    assert result.exit_code == 0
    events = [json.loads(line) for line in result.output.strip().splitlines()]
    assert [event["type"] for event in events] == [
        "run.started",
        "plan.created",
        "execution.completed",
        "reflection.completed",
        "run.completed",
    ]


def test_cli_run_can_show_tool_results(monkeypatch) -> None:
    runtime = FakeRuntime(
        [
            AgentEvent(
                type="execution.completed",
                data={
                    "tool_results": [
                        {
                            "name": "Read",
                            "ok": True,
                            "content": {"path": "README.md", "content": "hello from cli"},
                        }
                    ]
                },
            )
        ]
    )

    monkeypatch.setattr("agent_system.api.cli.create_runtime_from_config", lambda *args, **kwargs: runtime)

    result = runner.invoke(app, ["run", "Read README.md", "--show-tool-results"])

    assert result.exit_code == 0
    assert "tool.results" in result.output
    assert "Read [ok]" in result.output


def test_cli_run_outputs_tool_approval_event(monkeypatch) -> None:
    runtime = FakeRuntime(
        [
            AgentEvent(type="run.started", data={"task_id": "task-1"}),
            AgentEvent(type="plan.created", data={"goal": "Write notes"}),
            AgentEvent(type="execution.completed", data={"tool_result_count": 1, "tool_results": []}),
            AgentEvent(
                type="run.waiting_for_tool_approval",
                data={
                    "tool_approvals": [
                        {
                            "call_id": "write-1",
                            "tool": "Write",
                            "reason": "workspace write requires approval by policy",
                            "arguments_summary": {"path": "notes.txt", "content": "hello"},
                        }
                    ]
                },
            ),
        ]
    )

    monkeypatch.setattr("agent_system.api.cli.create_runtime_from_config", lambda *args, **kwargs: runtime)

    result = runner.invoke(app, ["run", "Write notes", "--json"])

    assert result.exit_code == 0
    events = [json.loads(line) for line in result.output.strip().splitlines()]
    assert events[-1]["type"] == "run.waiting_for_tool_approval"
    assert events[-1]["data"]["tool_approvals"][0]["tool"] == "Write"


def test_cli_runtime_chat_uses_runtime_without_event_dump(monkeypatch) -> None:
    runtime = FakeRuntime(
        [
            AgentEvent(
                type="execution.completed",
                data={
                    "tool_results": [
                        {
                            "name": "Read",
                            "ok": True,
                            "content": {"path": "README.md", "content": "hello runtime chat"},
                        }
                    ]
                },
            )
        ]
    )

    async def fake_synthesize_runtime_answer(**kwargs):
        return kwargs["fallback"]

    monkeypatch.setattr("agent_system.api.cli.create_runtime_from_config", lambda *args, **kwargs: runtime)
    monkeypatch.setattr("agent_system.api.cli._synthesize_runtime_answer", fake_synthesize_runtime_answer)

    result = runner.invoke(app, ["runtime-chat"], input="Read README.md\nexit\n")

    assert result.exit_code == 0
    assert "Assistant" in result.output
    assert "hello runtime chat" in result.output
    assert "run.started" not in result.output


def test_cli_runtime_chat_passes_raw_turns_to_runtime(monkeypatch) -> None:
    runtime = FakeRuntime([AgentEvent(type="run.completed", data={"task_id": "task-1", "confidence": 1.0})])

    monkeypatch.setattr("agent_system.api.cli.create_runtime_from_config", lambda *args, **kwargs: runtime)

    result = runner.invoke(app, ["runtime-chat"], input="first\nsecond\nexit\n")

    assert result.exit_code == 0
    assert runtime.contents == ["first", "second"]


def test_cli_runtime_chat_help_command_does_not_call_runtime(monkeypatch) -> None:
    runtime = FakeRuntime()

    monkeypatch.setattr("agent_system.api.cli.create_runtime_from_config", lambda *args, **kwargs: runtime)

    result = runner.invoke(app, ["runtime-chat"], input="/help\n/exit\n")

    assert result.exit_code == 0
    assert "Available runtime-chat commands" in result.output
    assert "/clear" in result.output
    assert "/tools" in result.output
    assert runtime.contents == []


def test_cli_runtime_chat_tool_list_request_does_not_call_runtime(monkeypatch) -> None:
    runtime = FakeRuntime()
    runtime.planner = SimpleNamespace(
        context=SimpleNamespace(
            tools=[
                ToolSchema(
                    name="Read",
                    description="Read a UTF-8 text file from the workspace.",
                )
            ]
        )
    )

    monkeypatch.setattr("agent_system.api.cli.create_runtime_from_config", lambda *args, **kwargs: runtime)

    result = runner.invoke(app, ["runtime-chat"], input="你有什么工具\n/exit\n")

    assert result.exit_code == 0
    assert "当前 Runtime 可用工具" in result.output
    assert "Read" in result.output
    assert runtime.contents == []


def test_cli_runtime_chat_tools_slash_command_shows_tools(monkeypatch) -> None:
    runtime = FakeRuntime()
    runtime.planner = SimpleNamespace(
        context=SimpleNamespace(
            tools=[
                ToolSchema(
                    name="Bash",
                    description="Run a shell command in the workspace.",
                    risk="high",
                    read_only=False,
                )
            ]
        )
    )

    monkeypatch.setattr("agent_system.api.cli.create_runtime_from_config", lambda *args, **kwargs: runtime)

    result = runner.invoke(app, ["runtime-chat"], input="/tools\n/exit\n")

    assert result.exit_code == 0
    assert "当前 Runtime 可用工具" in result.output
    assert "Bash" in result.output
    assert "risk=high" in result.output


def test_cli_runtime_chat_unknown_slash_command_does_not_call_runtime(monkeypatch) -> None:
    runtime = FakeRuntime()

    monkeypatch.setattr("agent_system.api.cli.create_runtime_from_config", lambda *args, **kwargs: runtime)

    result = runner.invoke(app, ["runtime-chat"], input="/bad\n/quit\n")

    assert result.exit_code == 0
    assert "Unknown command: /bad" in result.output
    assert "Type /help to see available commands." in result.output
    assert runtime.contents == []


def test_cli_runtime_chat_clear_command_resets_response_history(monkeypatch) -> None:
    history_lengths: list[int] = []
    runtime = FakeRuntime(
        [
            AgentEvent(
                type="execution.completed",
                data={
                    "tool_results": [
                        {
                            "name": "Read",
                            "ok": True,
                            "content": {"path": "README.md", "content": "hello"},
                        }
                    ]
                },
            )
        ]
    )

    async def fake_synthesize_runtime_answer(**kwargs):
        history_lengths.append(len(kwargs["history"]))
        return "ok"

    monkeypatch.setattr("agent_system.api.cli.create_runtime_from_config", lambda *args, **kwargs: runtime)
    monkeypatch.setattr("agent_system.api.cli._synthesize_runtime_answer", fake_synthesize_runtime_answer)

    result = runner.invoke(app, ["runtime-chat"], input="first\n/clear\nsecond\n/exit\n")

    assert result.exit_code == 0
    assert "Runtime chat history cleared." in result.output
    assert history_lengths == [0, 0]


def test_cli_runtime_chat_does_not_synthesize_failed_tool_results(monkeypatch) -> None:
    synthesize_called = False
    runtime = FakeRuntime(
        [
            AgentEvent(
                type="execution.completed",
                data={
                    "tool_results": [
                        {
                            "name": "Glob",
                            "ok": False,
                            "content": None,
                            "error": "missing required argument: pattern",
                        }
                    ]
                },
            )
        ]
    )

    async def fake_synthesize_runtime_answer(**kwargs):
        nonlocal synthesize_called
        synthesize_called = True
        return "rewritten"

    monkeypatch.setattr("agent_system.api.cli.create_runtime_from_config", lambda *args, **kwargs: runtime)
    monkeypatch.setattr("agent_system.api.cli._synthesize_runtime_answer", fake_synthesize_runtime_answer)

    result = runner.invoke(app, ["runtime-chat"], input="List target\n/exit\n")

    assert result.exit_code == 0
    assert "Glob 执行失败：missing required argument: pattern" in result.output
    assert synthesize_called is False


def test_cli_no_llm_option_is_removed() -> None:
    result = runner.invoke(app, ["run", "Inspect project", "--no-llm"])

    assert result.exit_code != 0


def test_cli_chat_command_is_removed() -> None:
    result = runner.invoke(app, ["chat"])

    assert result.exit_code != 0


def test_render_runtime_answer_from_tool_result() -> None:
    events = [
        AgentEvent(
            type="execution.completed",
            data={
                "tool_results": [
                    {
                        "name": "Read",
                        "ok": True,
                        "content": {"path": "README.md", "content": "hello"},
                    }
                ]
            },
        )
    ]

    assert _render_runtime_answer(events) == "README.md\nhello"


def test_render_runtime_answer_from_tool_approval_event() -> None:
    events = [
        AgentEvent(
            type="run.waiting_for_tool_approval",
            data={
                "tool_approvals": [
                    {
                        "call_id": "write-1",
                        "tool": "Write",
                        "reason": "workspace write requires approval by policy",
                        "arguments_summary": {"path": "notes.txt", "content": "hello"},
                    }
                ]
            },
        )
    ]

    answer = _render_runtime_answer(events)

    assert "需要工具审批" in answer
    assert "Write: workspace write requires approval by policy" in answer
    assert '"path": "notes.txt"' in answer


def test_render_runtime_answer_from_glob_result() -> None:
    events = [
        AgentEvent(
            type="execution.completed",
            data={
                "tool_results": [
                    {
                        "name": "Glob",
                        "ok": True,
                        "content": {
                            "path": "D:/code/ai-agent",
                            "pattern": "*",
                            "count": 2,
                            "matches": [
                                {"relative_path": "src", "type": "directory"},
                                {"relative_path": "README.md", "type": "file"},
                            ],
                        },
                    }
                ]
            },
        )
    ]

    answer = _render_runtime_answer(events)

    assert "D:/code/ai-agent 下匹配 * 的条目数：2" in answer
    assert "- src/" in answer
    assert "- README.md" in answer


def test_strip_reasoning_blocks() -> None:
    assert _strip_reasoning_blocks("a<think>hidden</think>b") == "ab"
