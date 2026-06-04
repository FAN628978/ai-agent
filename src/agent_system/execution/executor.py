from __future__ import annotations

import json
import re

from pydantic import BaseModel, Field

from agent_system.models import AgentState, Plan, Step, ToolCall, ToolResult
from agent_system.tools import ToolRouter


PATH_BOUNDARY_CHARS = ".,;:()[]{}\"'`，。；：（）【】{}"


class StepResult(BaseModel):
    step_id: str
    ok: bool
    summary: str


class ExecutionResult(BaseModel):
    step_results: list[StepResult] = Field(default_factory=list)
    tool_results: list[ToolResult] = Field(default_factory=list)

    def summary(self) -> dict[str, object]:
        return {
            "completed_steps": [step.step_id for step in self.step_results if step.ok],
            "failed_steps": [step.step_id for step in self.step_results if not step.ok],
            "tool_result_count": len(self.tool_results),
        }


class Executor:
    def __init__(self, tool_router: ToolRouter | None = None) -> None:
        self.tool_router = tool_router

    async def execute(self, plan: Plan, state: AgentState) -> ExecutionResult:
        step_results: list[StepResult] = []
        tool_results: list[ToolResult] = []

        for step in plan.steps:
            if step.id in state.completed_steps:
                continue

            step_tool_results = await self._execute_step_tools(step)
            if step_tool_results:
                tool_results.extend(step_tool_results)
                ok = all(result.ok for result in step_tool_results)
                step_results.append(
                    StepResult(
                        step_id=step.id,
                        ok=ok,
                        summary=self._tool_step_summary(step, step_tool_results),
                    )
                )
                if ok:
                    state.completed_steps.add(step.id)
                continue

            step_results.append(
                StepResult(
                    step_id=step.id,
                    ok=False,
                    summary=f"No executable tool call for step: {step.title}",
                )
            )

        return ExecutionResult(step_results=step_results, tool_results=tool_results)

    async def _execute_step_tools(self, step: Step) -> list[ToolResult]:
        if self.tool_router is None:
            return []

        results: list[ToolResult] = []
        if step.tool_calls:
            for call in step.tool_calls:
                results.append(await self.tool_router.invoke(call))
            return results

        for tool_name in step.suggested_tools:
            if tool_name not in {"Read", "Write", "Edit", "Grep", "Glob", "Bash"}:
                continue
            call = ToolCall(
                id=f"{step.id}:{tool_name}",
                name=tool_name,
                arguments=self._arguments_for_tool(tool_name, step),
            )
            results.append(await self.tool_router.invoke(call))
        return results

    def _arguments_for_tool(self, tool_name: str, step: Step) -> dict[str, object]:
        json_args = self._json_arguments(step.objective)
        if json_args is not None:
            return json_args

        if tool_name == "Read":
            return {"path": self._extract_path(step.objective)}
        if tool_name == "Write":
            return {
                "path": self._extract_path(step.objective),
                "content": self._extract_value(step.objective, "content", default=""),
            }
        if tool_name == "Edit":
            return {
                "path": self._extract_path(step.objective),
                "old_string": self._extract_value(step.objective, "old_string", default=""),
                "new_string": self._extract_value(step.objective, "new_string", default=""),
            }
        if tool_name == "Grep":
            return {
                "pattern": self._extract_value(step.objective, "pattern", default=step.objective),
                "path": self._extract_value(step.objective, "path", default="."),
            }
        if tool_name == "Glob":
            return {
                "pattern": self._extract_value(step.objective, "pattern", default="*"),
                "path": self._extract_value(step.objective, "path", default="."),
            }
        if tool_name == "Bash":
            return {"command": step.objective}
        return {}

    def _json_arguments(self, objective: str) -> dict[str, object] | None:
        stripped = objective.strip()
        if not stripped.startswith("{"):
            return None
        try:
            data = json.loads(stripped)
        except json.JSONDecodeError:
            return None
        return data if isinstance(data, dict) else None

    def _extract_path(self, objective: str) -> str:
        explicit = self._extract_value(objective, "path", default="")
        if explicit:
            return explicit

        quoted = re.search(r'["\']([^"\']+)["\']', objective)
        if quoted:
            return quoted.group(1)

        for token in objective.split():
            candidate = token.strip(PATH_BOUNDARY_CHARS)
            if "/" in candidate or "\\" in candidate or "." in candidate:
                return candidate
        return objective

    def _extract_value(self, objective: str, key: str, default: str) -> str:
        match = re.search(rf"{re.escape(key)}=([^\s]+)", objective)
        if match:
            return match.group(1).strip(PATH_BOUNDARY_CHARS)
        return default

    def _tool_step_summary(self, step: Step, tool_results: list[ToolResult]) -> str:
        failed = [result.name for result in tool_results if not result.ok]
        if failed:
            return f"Step failed with tool errors: {', '.join(failed)}"
        return f"Completed step with tools: {', '.join(result.name for result in tool_results)}"
