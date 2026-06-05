from agent_system.context import ContextAssembler, TokenBudget
from agent_system.models import UserRequest
from agent_system.skills import SkillSchema
from agent_system.tools.builtin import GlobTool, ReadFileTool


def test_context_assembler_injects_tool_schema_and_workspace() -> None:
    skill = SkillSchema(
        name="coding",
        description="Plan code changes.",
        triggers=["开发"],
        suggested_tools=["Read"],
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
    assert "Read" in messages[1].content
    assert "coding" in messages[1].content
    assert "D:/code/ai-agent" in messages[1].content
    assert messages[-1].content == "Read README.md"


def test_context_assembler_explains_read_and_glob_usage() -> None:
    assembler = ContextAssembler(
        tools=[ReadFileTool().schema, GlobTool().schema],
        workspace="D:/code/ai-agent",
    )
    request = UserRequest(
        session_id="session-1",
        user_id="user-1",
        workspace_id="workspace-1",
        content="List a target directory",
    )

    messages = assembler.planner_messages(request)

    planner_prompt = messages[1].content
    assert "Registered tool definitions from ToolRegistry" in planner_prompt
    assert "Read" in planner_prompt
    assert "Glob" in planner_prompt
    assert "description" in planner_prompt
    assert "risk" in planner_prompt
    assert "permission" in planner_prompt
    assert "input_schema" in planner_prompt
    assert "required_arguments" in planner_prompt
    assert "optional_arguments" in planner_prompt
    assert "Never invent tool names" in planner_prompt
    assert "Environment:" in planner_prompt


def test_context_assembler_injects_session_context() -> None:
    assembler = ContextAssembler()
    request = UserRequest(
        session_id="session-1",
        user_id="user-1",
        workspace_id="workspace-1",
        content="Continue",
    )

    messages = assembler.planner_messages(request, session_context="Previous plan goal: Read README.md")

    assert "Previous plan goal: Read README.md" in messages[-1].content
    assert "Current user request:\nContinue" in messages[-1].content


def test_context_assembler_instructs_planner_to_use_tools_for_follow_ups() -> None:
    assembler = ContextAssembler()
    request = UserRequest(
        session_id="session-1",
        user_id="user-1",
        workspace_id="workspace-1",
        content="Continue with more detail",
    )

    messages = assembler.planner_messages(request, session_context="Recent tool results: README.md, src/app.py")

    planner_prompt = messages[1].content
    assert "create concrete tool_calls" in planner_prompt
    assert "recent tool results" in planner_prompt.lower()


def test_token_budget_truncates_text() -> None:
    budget = TokenBudget(total=5)

    assert budget.reserve_text("abcdef") == "abcde"
    assert budget.remaining == 0
    assert budget.reserve_text("x") == ""
