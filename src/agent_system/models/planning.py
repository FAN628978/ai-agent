from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

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
    goal: str
    mode: RunMode
    steps: list[Step]
    assumptions: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)


class Critique(BaseModel):
    done: bool
    confidence: float
    issues: list[str] = Field(default_factory=list)
    next_action: Literal["finish", "retry", "replan", "ask_user"] = "finish"
