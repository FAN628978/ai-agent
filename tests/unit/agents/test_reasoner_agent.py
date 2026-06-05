import asyncio

from agent_system.agents import AgentReasoner
from agent_system.llm import ChatMessage, ChatResponse
from agent_system.models import Plan, RunMode, Step, ToolResult, UserRequest
from agent_system.tools.builtin import ReadFileTool


class FakeLLMClient:
    def __init__(self, content: str | list[str]) -> None:
        self.contents = [content] if isinstance(content, str) else content
        self.messages: list[ChatMessage] = []
        self.tools: list[dict[str, object]] | None = None
        self.calls = 0

    async def chat(
        self,
        messages: list[ChatMessage],
        *,
        max_tokens: int = 512,
        temperature: float = 0.2,
        tools: list[dict[str, object]] | None = None,
    ) -> ChatResponse:
        self.messages = messages
        self.tools = tools
        content = self.contents[min(self.calls, len(self.contents) - 1)]
        self.calls += 1
        return ChatResponse(model="fake", content=content)


class NativeToolCallLLMClient:
    async def chat(
        self,
        messages: list[ChatMessage],
        *,
        max_tokens: int = 512,
        temperature: float = 0.2,
        tools: list[dict[str, object]] | None = None,
    ) -> ChatResponse:
        del messages, max_tokens, temperature, tools
        return ChatResponse(
            model="fake",
            content="",
            tool_calls=[
                {
                    "id": "call-1",
                    "type": "function",
                    "function": {"name": "Read", "arguments": '{"path":"README.md"}'},
                }
            ],
        )


def make_request(content: str = "Inspect the target location") -> UserRequest:
    return UserRequest(
        session_id="session-1",
        user_id="user-1",
        workspace_id=".",
        content=content,
        mode=RunMode.ACT,
    )


def make_plan() -> Plan:
    return Plan(
        goal="Inspect the target location",
        mode=RunMode.ACT,
        steps=[Step(id="step-1", title="Inspect", objective="Inspect")],
    )


def test_reasoner_normalizes_tool_alias_without_task_rewrite() -> None:
    client = FakeLLMClient(
        """
        {
          "thought": "List files.",
          "tool_calls": [
            {"name": "DirList", "arguments": {}}
          ],
          "final_answer": null,
          "needs_user_input": []
        }
        """
    )
    reasoner = AgentReasoner(client)

    action = asyncio.run(
        reasoner.next_action(
            request=make_request(),
            session_context="",
            plan=make_plan(),
            tool_results=[],
            iteration=1,
        )
    )

    assert action.tool_calls[0].name == "Glob"
    assert action.tool_calls[0].arguments == {"path": "."}


def test_reasoner_preserves_invalid_tool_arguments_for_router_observation() -> None:
    client = FakeLLMClient(
        """
        {
          "thought": "Try reading.",
          "tool_calls": [
            {"name": "Read", "arguments": {}}
          ],
          "final_answer": null,
          "needs_user_input": []
        }
        """
    )
    reasoner = AgentReasoner(client)

    action = asyncio.run(
        reasoner.next_action(
            request=make_request(),
            session_context="Recent tool result: missing required argument: path",
            plan=make_plan(),
            tool_results=[
                ToolResult(
                    call_id="read-1",
                    name="Read",
                    ok=False,
                    content=None,
                    error="missing required argument: path",
                )
            ],
            iteration=2,
        )
    )

    assert action.tool_calls[0].name == "Read"
    assert action.tool_calls[0].arguments == {}


def test_reasoner_prompt_includes_environment_context() -> None:
    client = FakeLLMClient(
        """
        {
          "thought": "Done.",
          "tool_calls": [],
          "final_answer": "ok",
          "needs_user_input": []
        }
        """
    )
    reasoner = AgentReasoner(client, environment='{"workspace": "D:/workspace", "home": "C:/Users/me"}')

    asyncio.run(
        reasoner.next_action(
            request=make_request(),
            session_context="",
            plan=make_plan(),
            tool_results=[],
            iteration=1,
        )
    )

    assert '"workspace": "D:/workspace"' in client.messages[1].content
    assert "Registered tool definitions from ToolRegistry" in client.messages[1].content


def test_reasoner_passes_registered_tools_to_llm_tools_schema() -> None:
    client = FakeLLMClient(
        """
        {
          "thought": "Use Read.",
          "tool_calls": [{"name": "Read", "arguments": {"path": "README.md"}}],
          "final_answer": null,
          "needs_user_input": []
        }
        """
    )
    reasoner = AgentReasoner(client, tools=[ReadFileTool().schema])

    asyncio.run(
        reasoner.next_action(
            request=make_request("Read README.md"),
            session_context="",
            plan=make_plan(),
            tool_results=[],
            iteration=1,
        )
    )

    assert client.tools is not None
    function = client.tools[0]["function"]
    assert function["name"] == "Read"
    assert function["parameters"]["required"] == ["path"]
    assert "optional_arguments" in function["description"]


def test_reasoner_converts_native_tool_calls_to_action() -> None:
    reasoner = AgentReasoner(NativeToolCallLLMClient(), tools=[ReadFileTool().schema])

    action = asyncio.run(
        reasoner.next_action(
            request=make_request("Read README.md"),
            session_context="",
            plan=make_plan(),
            tool_results=[],
            iteration=1,
        )
    )

    assert action.tool_calls[0].name == "Read"
    assert action.tool_calls[0].arguments == {"path": "README.md"}


def test_reasoner_repairs_invalid_json_response() -> None:
    client = FakeLLMClient(
        [
            "not json",
            """
            {
              "thought": "Use a registered tool.",
              "tool_calls": [
                {"name": "Glob", "arguments": {"path": ".", "pattern": "*"}}
              ],
              "final_answer": null,
              "needs_user_input": []
            }
            """,
        ]
    )
    reasoner = AgentReasoner(client)

    action = asyncio.run(
        reasoner.next_action(
            request=make_request(),
            session_context="",
            plan=make_plan(),
            tool_results=[],
            iteration=1,
        )
    )

    assert client.calls == 2
    assert action.tool_calls[0].name == "Glob"
    assert "previous response was not a valid JSON action" in client.messages[-1].content
