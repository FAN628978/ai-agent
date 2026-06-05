import asyncio

from agent_system.agents import AgentReasoner
from agent_system.llm import ChatMessage, ChatResponse
from agent_system.models import Plan, RunMode, Step, StepResult, ToolResult, UserRequest


class FakeLLMClient:
    def __init__(self) -> None:
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
        return ChatResponse(
            model="fake",
            content="""
            {
              "thought": "Need to repair the tool call.",
              "tool_calls": [],
              "final_answer": "Need another action.",
              "needs_user_input": []
            }
            """,
        )


def make_request() -> UserRequest:
    return UserRequest(
        session_id="session-1",
        user_id="user-1",
        workspace_id="workspace-1",
        content="Inspect workspace",
        mode=RunMode.ACT,
    )


def make_plan() -> Plan:
    return Plan(
        goal="Inspect workspace",
        mode=RunMode.ACT,
        steps=[Step(id="step-1", title="Inspect", objective="Inspect workspace")],
    )


def test_reasoner_prompt_includes_execution_step_results() -> None:
    client = FakeLLMClient()
    reasoner = AgentReasoner(client)

    asyncio.run(
        reasoner.next_action(
            request=make_request(),
            session_context="",
            plan=make_plan(),
            tool_results=[],
            step_results=[
                StepResult(
                    step_id="step-1",
                    ok=False,
                    status="blocked",
                    error_type="dependency_failed",
                    summary="Step is blocked by failed dependencies: step-0",
                )
            ],
            iteration=1,
        )
    )

    user_prompt = client.messages[-1].content
    assert "Execution step results:" in user_prompt
    assert '"step_id": "step-1"' in user_prompt
    assert '"status": "blocked"' in user_prompt
    assert '"error_type": "dependency_failed"' in user_prompt


def test_reasoner_prompt_includes_unknown_and_validation_failures() -> None:
    client = FakeLLMClient()
    reasoner = AgentReasoner(client)

    asyncio.run(
        reasoner.next_action(
            request=make_request(),
            session_context="",
            plan=make_plan(),
            tool_results=[
                ToolResult(
                    call_id="bad-1",
                    name="read",
                    ok=False,
                    content={"available_tools": ["Read"], "error": "unknown tool: read"},
                    error="unknown tool: read",
                ),
                ToolResult(
                    call_id="read-1",
                    name="Read",
                    ok=False,
                    content={"required_args": ["path"], "input_schema": {"required": ["path"]}},
                    error="missing required argument: path",
                ),
            ],
            step_results=[
                StepResult(
                    step_id="step-1",
                    ok=False,
                    status="failed",
                    error_type="unknown_tool",
                    summary="Step failed with tool errors: read",
                ),
                StepResult(
                    step_id="step-2",
                    ok=False,
                    status="failed",
                    error_type="validation_failed",
                    summary="Step failed with tool errors: Read",
                ),
            ],
            iteration=1,
        )
    )

    system_prompt = client.messages[0].content
    user_prompt = client.messages[-1].content
    assert "If a step failed with unknown_tool" in system_prompt
    assert "Do not repeat the same invalid tool call" in system_prompt
    assert "unknown_tool" in user_prompt
    assert "validation_failed" in user_prompt
    assert "available_tools" in user_prompt
    assert "required_args" in user_prompt
