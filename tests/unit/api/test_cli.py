import json
import asyncio

from typer.testing import CliRunner

from agent_system.api.cli import (
    _render_runtime_answer,
    _runtime_request_content,
    _strip_reasoning_blocks,
    _chat_once,
    app,
)
from agent_system.llm import ChatMessage, ChatResponse
from agent_system.models import AgentEvent


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
    assert "file.read [ok]" in result.output


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


def test_runtime_request_content_includes_history() -> None:
    content = _runtime_request_content([("hello", "hi")], "next")

    assert "Conversation so far" in content
    assert "User: hello" in content
    assert "Current user request:\nnext" in content


def test_render_runtime_answer_from_tool_result() -> None:
    events = [
        AgentEvent(
            type="execution.completed",
            data={
                "tool_results": [
                    {
                        "name": "file.read",
                        "ok": True,
                        "content": {"path": "README.md", "content": "hello"},
                    }
                ]
            },
        )
    ]

    assert _render_runtime_answer(events) == "README.md\nhello"


class FakeChatClient:
    async def chat(
        self,
        messages: list[ChatMessage],
        *,
        max_tokens: int = 512,
        temperature: float = 0.2,
    ) -> ChatResponse:
        assert messages[-1].content == "hello"
        return ChatResponse(model="MiniMax-M2.5", content="<think>hidden</think>你好")


def test_chat_once_keeps_history_and_hides_reasoning() -> None:
    messages = [ChatMessage(role="system", content="system prompt")]

    answer = asyncio.run(
        _chat_once(
            client=FakeChatClient(),
            messages=messages,
            content="hello",
            max_tokens=64,
            temperature=0,
            history_limit=20,
            show_reasoning=False,
        )
    )

    assert answer == "你好"
    assert [message.role for message in messages] == ["system", "user", "assistant"]
    assert messages[-1].content == "你好"


def test_strip_reasoning_blocks() -> None:
    assert _strip_reasoning_blocks("a<think>hidden</think>b") == "ab"
