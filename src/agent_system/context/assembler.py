from __future__ import annotations

import json

from agent_system.context.budget import TokenBudget
from agent_system.llm import ChatMessage
from agent_system.models import UserRequest
from agent_system.prompts import PromptRegistry
from agent_system.skills.schemas import SkillSchema
from agent_system.tools.schemas import ToolSchema


class ContextAssembler:
    def __init__(
        self,
        prompts: PromptRegistry | None = None,
        tools: list[ToolSchema] | None = None,
        skills: list[SkillSchema] | None = None,
        workspace: str = ".",
        max_chars: int = 20000,
    ) -> None:
        self.prompts = prompts or PromptRegistry()
        self.tools = tools or []
        self.skills = skills or []
        self.workspace = workspace
        self.max_chars = max_chars

    def planner_messages(self, request: UserRequest) -> list[ChatMessage]:
        budget = TokenBudget(total=self.max_chars)
        tool_schemas = json.dumps(
            [tool.model_dump(mode="json") for tool in self.tools],
            ensure_ascii=False,
            indent=2,
        )
        skill_schemas = json.dumps(
            [skill.model_dump(mode="json") for skill in self.skills],
            ensure_ascii=False,
            indent=2,
        )
        system = self.prompts.render("system.md")
        planner = self.prompts.render(
            "planner.md",
            tool_schemas=budget.reserve_text(tool_schemas),
            skill_schemas=budget.reserve_text(skill_schemas),
            workspace=self.workspace,
        )
        return [
            ChatMessage(role="system", content=system),
            ChatMessage(role="system", content=planner),
            ChatMessage(role="user", content=request.content),
        ]
