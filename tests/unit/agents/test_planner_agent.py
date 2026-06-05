import asyncio

import pytest

from agent_system.agents import PlannerAgent
from agent_system.context import ContextAssembler
from agent_system.llm import ChatMessage, ChatResponse
from agent_system.models import RunMode, UserRequest
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
        **kwargs,
    ) -> ChatResponse:
        self.tools = kwargs.get("tools")
        self.messages = messages
        content = self.contents[min(self.calls, len(self.contents) - 1)]
        self.calls += 1
        return ChatResponse(model="MiniMax-M2.5", content=content)


class NativeToolCallLLMClient:
    def __init__(self) -> None:
        self.tools: list[dict[str, object]] | None = None

    async def chat(
        self,
        messages: list[ChatMessage],
        *,
        max_tokens: int = 512,
        temperature: float = 0.2,
        tools: list[dict[str, object]] | None = None,
    ) -> ChatResponse:
        del messages, max_tokens, temperature
        self.tools = tools
        return ChatResponse(
            model="MiniMax-M2.5",
            content="",
            tool_calls=[
                {
                    "id": "call-1",
                    "type": "function",
                    "function": {"name": "Read", "arguments": '{"path":"README.md"}'},
                }
            ],
        )


def make_request(content: str = "Create a project plan") -> UserRequest:
    return UserRequest(
        session_id="session-1",
        user_id="user-1",
        workspace_id="workspace-1",
        content=content,
        mode=RunMode.PLAN,
    )


def test_planner_requires_llm_client() -> None:
    planner = PlannerAgent()

    with pytest.raises(RuntimeError, match="requires an LLM client"):
        asyncio.run(planner.make_plan(make_request()))


def test_planner_uses_llm_json_plan() -> None:
    client = FakeLLMClient(
        """
        {
          "goal": "Create a project plan",
          "steps": [
            {
              "id": "step-1",
              "title": "Draft plan",
              "objective": "Create a short plan",
              "depends_on": [],
              "suggested_tools": ["Read"],
              "tool_calls": [
                {
                  "id": "call-1",
                  "name": "Read",
                  "arguments": {"path": "README.md"}
                }
              ],
              "risk": "low",
              "acceptance": ["Plan is created"]
            }
          ],
          "assumptions": ["LLM planner is enabled"],
          "risks": []
        }
        """
    )
    planner = PlannerAgent(llm_client=client)

    plan = asyncio.run(planner.make_plan(make_request()))

    assert plan.goal == "Create a project plan"
    assert plan.mode == RunMode.PLAN
    assert plan.steps[0].title == "Draft plan"
    assert plan.steps[0].tool_calls[0].name == "Read"
    assert plan.assumptions == ["LLM planner is enabled"]
    assert client.messages[0].role == "system"
    assert "Registered tool definitions from ToolRegistry" in client.messages[1].content


def test_planner_passes_registered_tools_to_llm_tools_schema() -> None:
    client = FakeLLMClient(
        """
        {
          "goal": "Read file",
          "steps": [
            {
              "id": "step-1",
              "title": "Read README",
              "objective": "Read README.md",
              "depends_on": [],
              "suggested_tools": ["Read"],
              "tool_calls": [{"id": "call-1", "name": "Read", "arguments": {"path": "README.md"}}],
              "risk": "low",
              "acceptance": ["File is read"]
            }
          ],
          "assumptions": [],
          "risks": []
        }
        """
    )
    planner = PlannerAgent(
        llm_client=client,
        context=ContextAssembler(tools=[ReadFileTool().schema]),
    )

    asyncio.run(planner.make_plan(make_request("Read README.md")))

    assert client.tools is not None
    assert client.tools[0]["type"] == "function"
    function = client.tools[0]["function"]
    assert function["name"] == "Read"
    assert function["parameters"]["required"] == ["path"]
    assert "required_arguments" in function["description"]


def test_planner_converts_native_tool_calls_to_plan() -> None:
    client = NativeToolCallLLMClient()
    planner = PlannerAgent(
        llm_client=client,
        context=ContextAssembler(tools=[ReadFileTool().schema]),
    )

    plan = asyncio.run(planner.make_plan(make_request("Read README.md")))

    assert client.tools is not None
    assert plan.steps[0].suggested_tools == ["Read"]
    assert plan.steps[0].tool_calls[0].name == "Read"
    assert plan.steps[0].tool_calls[0].arguments == {"path": "README.md"}


def test_planner_passes_session_context_to_llm_for_follow_up_planning() -> None:
    client = FakeLLMClient(
        [
            """
            {
              "goal": "Continue explanation",
              "steps": [],
              "assumptions": [],
              "risks": []
            }
            """,
            """
            {
              "goal": "Continue explanation",
              "steps": [
                {
                  "id": "step-1",
                  "title": "Continue from context",
                  "objective": "Use previous context to continue.",
                  "suggested_tools": [],
                  "tool_calls": [],
                  "risk": "low",
                  "acceptance": ["Continuation is planned"]
                }
              ],
              "assumptions": [],
              "risks": []
            }
            """,
        ]
    )
    planner = PlannerAgent(llm_client=client)

    asyncio.run(
        planner.make_plan(
            make_request("进一步"),
            session_context="Previous plan goal: 整个项目详细的讲解\nRecent tool results: README.md",
        )
    )

    assert any("Previous plan goal: 整个项目详细的讲解" in message.content for message in client.messages)
    assert "Current user request:\n进一步" in client.messages[-1].content


def test_planner_uses_llm_selected_tool_call_for_location_request() -> None:
    client = FakeLLMClient(
        """
        {
          "goal": "读取桌面的内容",
          "steps": [
            {
              "id": "step-1",
              "title": "List location contents",
              "objective": "List files selected by the model.",
              "suggested_tools": ["Glob"],
              "tool_calls": [
                {
                  "id": "call-1",
                  "name": "Glob",
                  "arguments": {"pattern": "*", "path": "Desktop"}
                }
              ],
              "risk": "low",
              "acceptance": ["The selected location has been listed."]
            }
          ],
          "assumptions": ["The model selected the tool and arguments."],
          "risks": []
        }
        """
    )
    planner = PlannerAgent(llm_client=client)

    plan = asyncio.run(planner.make_plan(make_request("读取桌面的内容")))

    assert plan.steps[0].suggested_tools == ["Glob"]
    assert plan.steps[0].tool_calls[0].name == "Glob"
    assert plan.steps[0].tool_calls[0].arguments == {"pattern": "*", "path": "Desktop"}


def test_llm_plan_without_tools_is_revised_by_llm_for_observation_request() -> None:
    client = FakeLLMClient(
        [
            """
            {
              "goal": "读取当前项目",
              "steps": [
                {
                  "id": "step-1",
                  "title": "Inspect project",
                  "objective": "Inspect the current project.",
                  "suggested_tools": [],
                  "tool_calls": [],
                  "risk": "low",
                  "acceptance": ["Project is inspected"]
                }
              ],
              "assumptions": [],
              "risks": []
            }
            """,
            """
            {
              "goal": "读取当前项目",
              "steps": [
                {
                  "id": "step-1",
                  "title": "List project files",
                  "objective": "List current workspace files.",
                  "suggested_tools": ["Glob"],
                  "tool_calls": [
                    {
                      "id": "call-1",
                      "name": "Glob",
                      "arguments": {"pattern": "*", "path": "."}
                    }
                  ],
                  "risk": "low",
                  "acceptance": ["Project files are listed"]
                }
              ],
              "assumptions": [],
              "risks": []
            }
            """,
        ]
    )
    planner = PlannerAgent(llm_client=client)

    plan = asyncio.run(planner.make_plan(make_request("读取当前项目")))

    assert client.calls == 2
    assert "previous plan did not include suggested_tools or tool_calls" in client.messages[-1].content.lower()
    assert plan.steps[0].suggested_tools == ["Glob"]
    assert plan.steps[0].tool_calls[0].arguments == {"pattern": "*", "path": "."}


def test_llm_tool_revision_prompt_distinguishes_read_and_glob() -> None:
    client = FakeLLMClient(
        [
            """
            {
              "goal": "桌面有什么",
              "steps": [
                {
                  "id": "step-1",
                  "title": "Answer",
                  "objective": "Answer the question.",
                  "suggested_tools": [],
                  "tool_calls": [],
                  "risk": "low",
                  "acceptance": ["Question is answered"]
                }
              ],
              "assumptions": [],
              "risks": []
            }
            """,
            """
            {
              "goal": "桌面有什么",
              "steps": [
                {
                  "id": "step-1",
                  "title": "Ask for workspace path",
                  "objective": "Ask the user for an explicit workspace-relative path.",
                  "suggested_tools": [],
                  "tool_calls": [],
                  "risk": "low",
                  "acceptance": ["Workspace path requirement is clarified"]
                }
              ],
              "assumptions": ["Need an explicit workspace-relative path for named locations outside the workspace."],
              "risks": []
            }
            """,
        ]
    )
    planner = PlannerAgent(llm_client=client)

    asyncio.run(planner.make_plan(make_request("桌面有什么")))

    repair_prompt = client.messages[-1].content
    assert "registered tool definitions" in repair_prompt
    assert "input_schema" in repair_prompt
    assert "ask for clarification instead of inventing access" in repair_prompt


def test_planner_repairs_invalid_llm_output_with_llm() -> None:
    client = FakeLLMClient(
        [
            "not json",
            """
            {
              "goal": "Create a project plan",
              "steps": [
                {
                  "id": "step-1",
                  "title": "List files",
                  "objective": "List workspace files.",
                  "suggested_tools": ["Glob"],
                  "tool_calls": [
                    {
                      "id": "call-1",
                      "name": "Glob",
                      "arguments": {"pattern": "*", "path": "."}
                    }
                  ],
                  "risk": "low",
                  "acceptance": ["Files are listed"]
                }
              ],
              "assumptions": [],
              "risks": []
            }
            """,
        ]
    )
    planner = PlannerAgent(llm_client=client)

    plan = asyncio.run(planner.make_plan(make_request()))

    assert client.calls == 2
    assert "previous response was not a valid json plan" in client.messages[-1].content.lower()
    assert plan.steps[0].tool_calls[0].name == "Glob"


def test_planner_repairs_json_fragment_that_is_not_a_plan() -> None:
    client = FakeLLMClient(
        [
            '{"pattern": "*", "path": "."}',
            """
            {
              "goal": "Inspect workspace",
              "steps": [
                {
                  "id": "step-1",
                  "title": "List files",
                  "objective": "List workspace files.",
                  "suggested_tools": ["Glob"],
                  "tool_calls": [
                    {
                      "id": "call-1",
                      "name": "Glob",
                      "arguments": {"pattern": "*", "path": "."}
                    }
                  ],
                  "risk": "low",
                  "acceptance": ["Files are listed"]
                }
              ],
              "assumptions": [],
              "risks": []
            }
            """,
        ]
    )
    planner = PlannerAgent(llm_client=client)

    plan = asyncio.run(planner.make_plan(make_request("读取当前项目")))

    assert client.calls == 2
    assert plan.goal == "Inspect workspace"
    assert plan.steps[0].tool_calls[0].name == "Glob"


def test_planner_extracts_plan_from_multiple_json_fragments() -> None:
    client = FakeLLMClient(
        """
        {"pattern": "*", "path": "."}
        {
          "goal": "Inspect workspace",
          "steps": [
            {
              "id": "step-1",
              "title": "List files",
              "objective": "List workspace files.",
              "suggested_tools": ["Glob"],
              "tool_calls": [
                {
                  "id": "call-1",
                  "name": "Glob",
                  "arguments": {"pattern": "*", "path": "."}
                }
              ],
              "risk": "low",
              "acceptance": ["Files are listed"]
            }
          ],
          "assumptions": [],
          "risks": []
        }
        """
    )
    planner = PlannerAgent(llm_client=client)

    plan = asyncio.run(planner.make_plan(make_request("读取当前项目")))

    assert client.calls == 1
    assert plan.goal == "Inspect workspace"
    assert plan.steps[0].tool_calls[0].name == "Glob"


def test_planner_normalizes_common_llm_json_shape() -> None:
    client = FakeLLMClient(
        """
        {
          "goal": "Create a project plan",
          "steps": [
            {
              "id": 1,
              "title": "Draft plan",
              "objective": "Create a short plan",
              "depends_on": [0],
              "suggested_tools": null,
              "risk": "LOW",
              "acceptance": "Plan is created"
            }
          ],
          "assumptions": "LLM planner is enabled",
          "risks": [{"category": "schedule", "mitigation": "keep scope small"}]
        }
        """
    )
    planner = PlannerAgent(llm_client=client)

    plan = asyncio.run(planner.make_plan(make_request()))

    assert plan.steps[0].id == "1"
    assert plan.steps[0].depends_on == ["0"]
    assert plan.steps[0].suggested_tools == []
    assert plan.steps[0].risk == "low"
    assert plan.steps[0].acceptance == ["Plan is created"]
    assert plan.assumptions == ["LLM planner is enabled"]
    assert plan.risks == ['{"category": "schedule", "mitigation": "keep scope small"}']


def test_planner_normalizes_llm_tool_calls() -> None:
    client = FakeLLMClient(
        """
        {
          "goal": "Read file",
          "steps": [
            {
              "id": 1,
              "title": "Read README",
              "objective": "Read README.md",
              "depends_on": [],
              "suggested_tools": ["Read"],
              "tool_calls": [
                {
                  "name": "Read",
                  "arguments": {"path": "README.md"}
                }
              ],
              "risk": "low",
              "acceptance": ["File is read"]
            }
          ],
          "assumptions": [],
          "risks": []
        }
        """
    )
    planner = PlannerAgent(llm_client=client)

    plan = asyncio.run(planner.make_plan(make_request()))

    assert plan.steps[0].tool_calls[0].id == "1:Read:1"
    assert plan.steps[0].tool_calls[0].name == "Read"
    assert plan.steps[0].tool_calls[0].arguments == {"path": "README.md"}


def test_planner_normalizes_common_tool_call_shape_and_aliases() -> None:
    client = FakeLLMClient(
        """
        {
          "goal": "List desktop",
          "steps": [
            {
              "id": "step-1",
              "title": "List desktop",
              "objective": "List desktop files.",
              "depends_on": [],
              "suggested_tools": ["shell"],
              "tool_calls": [
                {
                  "tool": "shell",
                  "params": {"command": "ls ~/Desktop"}
                }
              ],
              "risk": "low",
              "acceptance": ["Desktop is listed"]
            }
          ],
          "assumptions": [],
          "risks": []
        }
        """
    )
    planner = PlannerAgent(llm_client=client)

    plan = asyncio.run(planner.make_plan(make_request("桌面有什么")))

    assert plan.steps[0].suggested_tools == ["Bash"]
    assert plan.steps[0].tool_calls[0].name == "Bash"
    assert plan.steps[0].tool_calls[0].arguments == {"command": "ls ~/Desktop"}
