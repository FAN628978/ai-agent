import asyncio

from agent_system.agents import AgentReasoner, PlannerAgent
from agent_system.llm import ChatMessage, ChatResponse
from agent_system.models import Plan, RunMode, Step, ToolCall, UserRequest
from agent_system.tools import ToolRegistry, ToolRouter
from agent_system.tools.builtin import BashTool, EditFileTool, GlobTool, GrepSearchTool, ReadFileTool, WriteFileTool
from agent_system.tools.normalization import clean_tool_name


class FakeLLMClient:
    def __init__(self, content: str) -> None:
        self.content = content
        self.messages: list[ChatMessage] = []

    async def chat(
        self,
        messages: list[ChatMessage],
        *,
        max_tokens: int = 512,
        temperature: float = 0.2,
        tools: list[dict[str, object]] | None = None,
    ) -> ChatResponse:
        del max_tokens, temperature, tools
        self.messages = messages
        return ChatResponse(model="fake", content=self.content)


def make_request(content: str = "Inspect files") -> UserRequest:
    return UserRequest(
        session_id="session-1",
        user_id="user-1",
        workspace_id="workspace-1",
        content=content,
        mode=RunMode.ACT,
    )


def make_plan() -> Plan:
    return Plan(
        goal="Inspect files",
        mode=RunMode.ACT,
        steps=[Step(id="step-1", title="Inspect", objective="Inspect files")],
    )


def register_all_tools() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(ReadFileTool())
    registry.register(WriteFileTool())
    registry.register(EditFileTool())
    registry.register(GrepSearchTool())
    registry.register(GlobTool())
    registry.register(BashTool())
    return registry


def test_clean_tool_name_strips_only() -> None:
    assert clean_tool_name("Read") == "Read"
    assert clean_tool_name(" Read ") == "Read"
    assert clean_tool_name("read") == "read"
    assert clean_tool_name("ls") == "ls"
    assert clean_tool_name("") == ""


def test_tool_router_returns_unknown_for_unregistered_alias(tmp_path) -> None:
    registry = register_all_tools()
    router = ToolRouter(registry, tmp_path)

    result = asyncio.run(router.invoke(ToolCall(id="call-1", name="read", arguments={"path": "README.md"})))

    assert result.ok is False
    assert result.error == "unknown tool: read"
    assert result.content["available_tools"] == ["Read", "Write", "Edit", "Grep", "Glob", "Bash"]
    assert [tool["name"] for tool in result.content["tool_definitions"]] == [
        "Read",
        "Write",
        "Edit",
        "Grep",
        "Glob",
        "Bash",
    ]


def test_planner_preserves_raw_tool_call_names() -> None:
    client = FakeLLMClient(
        """
        {
          "goal": "Inspect files",
          "steps": [
            {
              "id": "step-1",
              "title": "Read files",
              "objective": "Read files",
              "depends_on": [],
              "suggested_tools": ["read", "Read"],
              "tool_calls": [
                {"id": "call-1", "name": "read", "arguments": {"path": "README.md"}},
                {"id": "call-2", "name": "Read", "arguments": {"path": "README.md"}}
              ],
              "risk": "low",
              "acceptance": ["Done"]
            }
          ],
          "assumptions": [],
          "risks": []
        }
        """
    )
    planner = PlannerAgent(llm_client=client)

    plan = asyncio.run(planner.make_plan(make_request()))

    assert [call.name for call in plan.steps[0].tool_calls] == ["read", "Read"]
    assert plan.steps[0].suggested_tools == ["read", "Read"]


def test_reasoner_preserves_raw_tool_call_names() -> None:
    client = FakeLLMClient(
        """
        {
          "thought": "Search files.",
          "tool_calls": [
            {"id": "call-1", "name": "search", "arguments": {"pattern": "abc"}},
            {"id": "call-2", "name": "Grep", "arguments": {"pattern": "abc"}}
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

    assert [call.name for call in action.tool_calls] == ["search", "Grep"]


def test_tool_router_preserves_argument_normalization(tmp_path) -> None:
    (tmp_path / "README.md").write_text("abc\n", encoding="utf-8")
    registry = ToolRegistry()
    registry.register(ReadFileTool())
    registry.register(GrepSearchTool())
    registry.register(GlobTool())
    router = ToolRouter(registry, tmp_path)

    grep = asyncio.run(router.invoke(ToolCall(id="grep-1", name="Grep", arguments={"pattern": "abc"})))
    glob = asyncio.run(router.invoke(ToolCall(id="glob-1", name="Glob", arguments={})))
    read = asyncio.run(router.invoke(ToolCall(id="read-1", name="Read", arguments={"file_path": "README.md"})))

    assert grep.ok is True
    assert grep.metadata["audit"]["arguments_summary"]["path"] == "."
    assert glob.ok is True
    assert glob.metadata["audit"]["arguments_summary"]["path"] == "."
    assert read.ok is True
    assert read.metadata["audit"]["arguments_summary"] == {"path": "README.md"}
