from agent_system.context import ContextAssembler, TokenBudget
from agent_system.models import UserRequest
from agent_system.skills import SkillSchema
from agent_system.tools.builtin import ReadFileTool


def test_context_assembler_injects_tool_schema_and_workspace() -> None:
    skill = SkillSchema(
        name="coding",
        description="Plan code changes.",
        triggers=["开发"],
        suggested_tools=["file.read"],
    )
    assembler = ContextAssembler(
        tools=[ReadFileTool().schema],
        skills=[skill],
        workspace="D:/code/ai-agent",
    )
    request = UserRequest(
        session_id="session-1",
        user_id="user-1",
        workspace_id="workspace-1",
        content="Read README.md",
    )

    messages = assembler.planner_messages(request)

    assert [message.role for message in messages] == ["system", "system", "user"]
    assert "file.read" in messages[1].content
    assert "coding" in messages[1].content
    assert "D:/code/ai-agent" in messages[1].content
    assert messages[-1].content == "Read README.md"


def test_token_budget_truncates_text() -> None:
    budget = TokenBudget(total=5)

    assert budget.reserve_text("abcdef") == "abcde"
    assert budget.remaining == 0
    assert budget.reserve_text("x") == ""
