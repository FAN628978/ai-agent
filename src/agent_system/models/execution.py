from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from agent_system.models.tools import ToolResult


class StepResult(BaseModel):
    step_id: str
    ok: bool
    summary: str
    status: Literal["success", "failed", "blocked", "skipped", "waiting"] = "success"
    error_type: str | None = None

    def model_post_init(self, __context: Any) -> None:
        if "status" not in self.model_fields_set and not self.ok:
            self.status = "failed"


class ExecutionResult(BaseModel):
    step_results: list[StepResult] = Field(default_factory=list)
    tool_results: list[ToolResult] = Field(default_factory=list)

    def summary(self) -> dict[str, object]:
        error_types = [
            step.error_type
            for step in self.step_results
            if step.error_type is not None
        ]
        return {
            "completed_steps": [step.step_id for step in self.step_results if step.ok],
            "failed_steps": [step.step_id for step in self.step_results if not step.ok],
            "tool_result_count": len(self.tool_results),
            "blocked_steps": [step.step_id for step in self.step_results if step.status == "blocked"],
            "waiting_steps": [step.step_id for step in self.step_results if step.status == "waiting"],
            "error_types": list(dict.fromkeys(error_types)),
        }
