from __future__ import annotations

from typing import Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field

from agent_system.models.request import RunMode
from agent_system.models.tools import ToolCall


class Step(BaseModel):
    id: str
    title: str
    objective: str
    depends_on: list[str] = Field(default_factory=list)
    suggested_tools: list[str] = Field(default_factory=list)
    tool_calls: list[ToolCall] = Field(default_factory=list)
    risk: Literal["low", "medium", "high"] = "low"
    acceptance: list[str] = Field(default_factory=list)


class Plan(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    task_goal: str = Field(validation_alias=AliasChoices("task_goal", "goal"))
    mode: RunMode
    steps: list[Step]
    expected_outputs: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    success_criteria: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)

    @property
    def goal(self) -> str:
        return self.task_goal


class Critique(BaseModel):
    done: bool
    confidence: float
    reason: str = ""
    missing_items: list[str] = Field(default_factory=list)
    suggested_next_action: str = ""
    issues: list[str] = Field(default_factory=list)
    next_action: Literal["finish", "retry", "replan", "ask_user"] = "finish"
