import asyncio

from agent_system.agents import PlannerAgent
from agent_system.llm import ChatMessage, ChatResponse
from agent_system.models import RunMode, UserRequest


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
    ) -> ChatResponse:
        self.messages = messages
        return ChatResponse(model="MiniMax-M2.5", content=self.content)


def make_request() -> UserRequest:
    return UserRequest(
        session_id="session-1",
        user_id="user-1",
        workspace_id="workspace-1",
        content="Create a project plan",
        mode=RunMode.PLAN,
    )


def test_rule_planner_suggests_file_read_for_read_requests() -> None:
    planner = PlannerAgent()
    request = UserRequest(
        session_id="session-1",
        user_id="user-1",
        workspace_id="workspace-1",
        content="Read README.md",
    )

    plan = asyncio.run(planner.make_plan(request))

    assert plan.steps[0].suggested_tools == ["file.read"]


def test_rule_planner_suggests_grep_for_search_requests() -> None:
    planner = PlannerAgent()
    request = UserRequest(
        session_id="session-1",
        user_id="user-1",
        workspace_id="workspace-1",
        content="search pattern=Agent path=README.md",
    )

    plan = asyncio.run(planner.make_plan(request))

    assert plan.steps[0].suggested_tools == ["grep.search"]


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
              "suggested_tools": [],
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
    assert plan.assumptions == ["LLM planner is enabled"]
    assert client.messages[0].role == "system"
    assert "Available tools" in client.messages[1].content


def test_planner_falls_back_when_llm_output_is_invalid() -> None:
    planner = PlannerAgent(llm_client=FakeLLMClient("not json"))

    plan = asyncio.run(planner.make_plan(make_request()))

    assert plan.goal == "Create a project plan"
    assert plan.steps[0].id == "step-1"
    assert plan.assumptions == ["LLM planner failed; using the built-in rule-based planner."]
    assert plan.risks == ["LLM planner response did not contain a JSON object."]


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
              "suggested_tools": ["file.read"],
              "tool_calls": [
                {
                  "name": "file.read",
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

    assert plan.steps[0].tool_calls[0].id == "1:file.read:1"
    assert plan.steps[0].tool_calls[0].name == "file.read"
    assert plan.steps[0].tool_calls[0].arguments == {"path": "README.md"}
