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


def test_cli_plan_outputs_plan_events() -> None:
    result = runner.invoke(app, ["plan", "Inspect project", "--no-llm", "--json"])

    assert result.exit_code == 0
    events = [json.loads(line) for line in result.output.strip().splitlines()]
    assert [event["type"] for event in events] == [
        "run.started",
        "plan.created",
        "run.waiting_for_approval",
    ]
    assert events[1]["data"]["goal"] == "Inspect project"


def test_cli_run_outputs_runtime_events() -> None:
    result = runner.invoke(app, ["run", "Inspect project", "--no-llm", "--json"])

    assert result.exit_code == 0
    events = [json.loads(line) for line in result.output.strip().splitlines()]
    assert [event["type"] for event in events] == [
        "run.started",
        "plan.created",
        "execution.completed",
        "reflection.completed",
        "run.completed",
    ]


def test_cli_run_can_execute_file_read_tool(tmp_path) -> None:
    (tmp_path / "README.md").write_text("hello from cli", encoding="utf-8")

    result = runner.invoke(
        app,
        [
            "run",
            "Read README.md",
            "--workspace-id",
            str(tmp_path),
            "--no-llm",
            "--json",
        ],
    )

    assert result.exit_code == 0
    events = [json.loads(line) for line in result.output.strip().splitlines()]
    execution_event = next(event for event in events if event["type"] == "execution.completed")
    assert execution_event["data"]["tool_result_count"] == 1


def test_cli_run_can_show_tool_results(tmp_path) -> None:
    (tmp_path / "README.md").write_text("hello from cli", encoding="utf-8")

    result = runner.invoke(
        app,
        [
            "run",
            "Read README.md",
            "--workspace-id",
            str(tmp_path),
            "--no-llm",
            "--show-tool-results",
        ],
    )

    assert result.exit_code == 0
    assert "tool.results" in result.output
    assert "Read [ok]" in result.output


def test_cli_runtime_chat_uses_runtime_without_event_dump(tmp_path) -> None:
    (tmp_path / "README.md").write_text("hello runtime chat", encoding="utf-8")

    result = runner.invoke(
        app,
        [
            "runtime-chat",
            "--workspace-id",
            str(tmp_path),
            "--no-llm",
        ],
        input="Read README.md\nexit\n",
    )

    assert result.exit_code == 0
    assert "Assistant" in result.output
    assert "hello runtime chat" in result.output
    assert "run.started" not in result.output


def test_cli_runtime_chat_passes_raw_turns_to_runtime(monkeypatch) -> None:
    contents: list[str] = []

    class FakeRuntime:
        async def run(self, request):
            contents.append(request.content)
            yield AgentEvent(type="run.completed", data={"task_id": "task-1", "confidence": 1.0})

    def fake_create_runtime_from_config(*args, **kwargs):
        return FakeRuntime()

    monkeypatch.setattr("agent_system.api.cli.create_runtime_from_config", fake_create_runtime_from_config)

    result = runner.invoke(
        app,
        ["runtime-chat", "--no-llm"],
        input="first\nsecond\nexit\n",
    )

    assert result.exit_code == 0
    assert contents == ["first", "second"]


def test_cli_runtime_chat_help_command_does_not_call_runtime(monkeypatch) -> None:
    contents: list[str] = []

    class FakeRuntime:
        async def run(self, request):
            contents.append(request.content)
            yield AgentEvent(type="run.completed", data={"task_id": "task-1", "confidence": 1.0})

    def fake_create_runtime_from_config(*args, **kwargs):
        return FakeRuntime()

    monkeypatch.setattr("agent_system.api.cli.create_runtime_from_config", fake_create_runtime_from_config)

    result = runner.invoke(
        app,
        ["runtime-chat", "--no-llm"],
        input="/help\n/exit\n",
    )

    assert result.exit_code == 0
    assert "Available runtime-chat commands" in result.output
    assert "/clear" in result.output
    assert "/tools" in result.output
    assert contents == []


def test_cli_runtime_chat_tool_list_request_does_not_call_runtime(monkeypatch) -> None:
    contents: list[str] = []

    class FakeRuntime:
        planner = SimpleNamespace(
            context=SimpleNamespace(
                tools=[
                    ToolSchema(
                        name="Read",
                        description="Read a UTF-8 text file from the workspace.",
                    )
                ]
            )
        )

        async def run(self, request):
            contents.append(request.content)
            yield AgentEvent(type="run.completed", data={"task_id": "task-1", "confidence": 1.0})

    def fake_create_runtime_from_config(*args, **kwargs):
        return FakeRuntime()

    monkeypatch.setattr("agent_system.api.cli.create_runtime_from_config", fake_create_runtime_from_config)

    result = runner.invoke(
        app,
        ["runtime-chat", "--no-llm"],
        input="你有什么工具\n/exit\n",
    )

    assert result.exit_code == 0
    assert "当前 Runtime 可用工具" in result.output
    assert "Read" in result.output
    assert contents == []


def test_cli_runtime_chat_tools_slash_command_shows_tools(monkeypatch) -> None:
    class FakeRuntime:
        planner = SimpleNamespace(
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

        async def run(self, request):
            yield AgentEvent(type="run.completed", data={"task_id": "task-1", "confidence": 1.0})

    def fake_create_runtime_from_config(*args, **kwargs):
        return FakeRuntime()

    monkeypatch.setattr("agent_system.api.cli.create_runtime_from_config", fake_create_runtime_from_config)

    result = runner.invoke(
        app,
        ["runtime-chat", "--no-llm"],
        input="/tools\n/exit\n",
    )

    assert result.exit_code == 0
    assert "当前 Runtime 可用工具" in result.output
    assert "Bash" in result.output
    assert "risk=high" in result.output


def test_cli_runtime_chat_unknown_slash_command_does_not_call_runtime(monkeypatch) -> None:
    contents: list[str] = []

    class FakeRuntime:
        async def run(self, request):
            contents.append(request.content)
            yield AgentEvent(type="run.completed", data={"task_id": "task-1", "confidence": 1.0})

    def fake_create_runtime_from_config(*args, **kwargs):
        return FakeRuntime()

    monkeypatch.setattr("agent_system.api.cli.create_runtime_from_config", fake_create_runtime_from_config)

    result = runner.invoke(
        app,
        ["runtime-chat", "--no-llm"],
        input="/bad\n/quit\n",
    )

    assert result.exit_code == 0
    assert "Unknown command: /bad" in result.output
    assert "Type /help to see available commands." in result.output
    assert contents == []


def test_cli_runtime_chat_clear_command_resets_response_history(monkeypatch) -> None:
    history_lengths: list[int] = []

    class FakeRuntime:
        async def run(self, request):
            yield AgentEvent(type="run.completed", data={"task_id": "task-1", "confidence": 1.0})

    async def fake_synthesize_runtime_answer(**kwargs):
        history_lengths.append(len(kwargs["history"]))
        return "ok"

    def fake_create_runtime_from_config(*args, **kwargs):
        return FakeRuntime()

    monkeypatch.setattr("agent_system.api.cli.create_runtime_from_config", fake_create_runtime_from_config)
    monkeypatch.setattr("agent_system.api.cli._synthesize_runtime_answer", fake_synthesize_runtime_answer)

    result = runner.invoke(
        app,
        ["runtime-chat"],
        input="first\n/clear\nsecond\n/exit\n",
    )

    assert result.exit_code == 0
    assert "Runtime chat history cleared." in result.output
    assert history_lengths == [0, 0]


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
