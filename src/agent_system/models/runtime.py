from __future__ import annotations

from pydantic import BaseModel, Field

from agent_system.models.execution import StepResult
from agent_system.models.planning import Plan
from agent_system.models.request import RunMode
from agent_system.models.tools import ToolResult


class AgentState(BaseModel):
    session_id: str
    task_id: str
    mode: RunMode
    plan: Plan | None = None
    completed_steps: set[str] = Field(default_factory=set)
    step_results: list[StepResult] = Field(default_factory=list)
    tool_results: list[ToolResult] = Field(default_factory=list)
    iteration: int = 0
    max_iterations: int = 20
