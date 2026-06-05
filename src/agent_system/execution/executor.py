from __future__ import annotations

import json
import re
from typing import Literal

from agent_system.models import AgentState, ExecutionResult, Plan, Step, StepResult, ToolCall, ToolResult
from agent_system.tools import ToolRouter


PATH_BOUNDARY_CHARS = ".,;:()[]{}\"'`，。；：（）【】{}"


class Executor:
    def __init__(self, tool_router: ToolRouter | None = None) -> None:
        self.tool_router = tool_router

    async def execute(self, plan: Plan, state: AgentState) -> ExecutionResult:
        step_results: list[StepResult] = []
        tool_results: list[ToolResult] = []
        result_by_step: dict[str, StepResult] = {}
        missing_dependencies, cycle_steps, ordered_steps = _dependency_plan(plan.steps)

        for step in ordered_steps:
            if step.id in state.completed_steps:
                continue
            if step.id in cycle_steps:
                result = StepResult(
                    step_id=step.id,
                    ok=False,
                    status="blocked",
                    error_type="dependency_cycle",
                    summary=f"Step is blocked by a dependency cycle: {step.title}",
                )
                step_results.append(result)
                result_by_step[step.id] = result
                continue
            if missing_dependencies.get(step.id):
                missing = ", ".join(missing_dependencies[step.id])
                result = StepResult(
                    step_id=step.id,
                    ok=False,
                    status="blocked",
                    error_type="dependency_missing",
                    summary=f"Step is blocked by missing dependencies: {missing}",
                )
                step_results.append(result)
                result_by_step[step.id] = result
                continue
            failed_dependencies = [
                dependency
                for dependency in step.depends_on
                if not _dependency_succeeded(dependency, result_by_step, state)
            ]
            if failed_dependencies:
                failed = ", ".join(failed_dependencies)
                result = StepResult(
                    step_id=step.id,
                    ok=False,
                    status="blocked",
                    error_type="dependency_failed",
                    summary=f"Step is blocked by failed dependencies: {failed}",
                )
                step_results.append(result)
                result_by_step[step.id] = result
                continue

            step_tool_results = await self._execute_step_tools(step)
            if step_tool_results:
                tool_results.extend(step_tool_results)
                ok = all(result.ok for result in step_tool_results)
                error_type = _classify_tool_failure(step_tool_results)
                status: Literal["success", "failed", "blocked", "skipped", "waiting"] = (
                    "success" if ok else "waiting" if error_type == "approval_required" else "failed"
                )
                step_result = StepResult(
                    step_id=step.id,
                    ok=ok,
                    status=status,
                    error_type=error_type,
                    summary=self._tool_step_summary(step, step_tool_results),
                )
                step_results.append(step_result)
                result_by_step[step.id] = step_result
                if ok:
                    state.completed_steps.add(step.id)
                if _has_approval_required(step_tool_results):
                    break
                continue

            step_result = StepResult(
                step_id=step.id,
                ok=False,
                status="failed",
                error_type="no_executable_tool",
                summary=f"No executable tool call for step: {step.title}",
            )
            step_results.append(step_result)
            result_by_step[step.id] = step_result

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
            try:
                self.tool_router.registry.get(tool_name)
            except KeyError:
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
        if _has_approval_required(tool_results):
            return "Step is waiting for tool approval."
        failed = [result.name for result in tool_results if not result.ok]
        if failed:
            return f"Step failed with tool errors: {', '.join(failed)}"
        return f"Completed step with tools: {', '.join(result.name for result in tool_results)}"


def _has_approval_required(tool_results: list[ToolResult]) -> bool:
    return any(_is_approval_required(result) for result in tool_results)


def _is_approval_required(result: ToolResult) -> bool:
    if isinstance(result.content, dict) and result.content.get("approval_required") is True:
        return True
    audit = result.metadata.get("audit", {})
    return isinstance(audit, dict) and audit.get("status") == "approval_required"


def _dependency_plan(steps: list[Step]) -> tuple[dict[str, list[str]], set[str], list[Step]]:
    step_by_id = {step.id: step for step in steps}
    original_order = {step.id: index for index, step in enumerate(steps)}
    missing_dependencies = {
        step.id: [dependency for dependency in step.depends_on if dependency not in step_by_id]
        for step in steps
    }
    missing_dependencies = {
        step_id: dependencies
        for step_id, dependencies in missing_dependencies.items()
        if dependencies
    }

    incoming: dict[str, set[str]] = {
        step.id: {dependency for dependency in step.depends_on if dependency in step_by_id}
        for step in steps
    }
    dependents: dict[str, list[str]] = {step.id: [] for step in steps}
    for step_id, dependencies in incoming.items():
        for dependency in dependencies:
            if step_id not in dependents[dependency]:
                dependents[dependency].append(step_id)

    ready = sorted(
        [step_id for step_id, dependencies in incoming.items() if not dependencies],
        key=original_order.__getitem__,
    )
    ordered_ids: list[str] = []
    while ready:
        step_id = ready.pop(0)
        ordered_ids.append(step_id)
        for dependent_id in sorted(dependents[step_id], key=original_order.__getitem__):
            incoming[dependent_id].remove(step_id)
            if not incoming[dependent_id]:
                ready.append(dependent_id)
        ready.sort(key=original_order.__getitem__)

    cycle_steps = set(step_by_id) - set(ordered_ids)
    ordered_ids.extend(step.id for step in steps if step.id in cycle_steps)
    return missing_dependencies, cycle_steps, [step_by_id[step_id] for step_id in ordered_ids]


def _dependency_succeeded(
    dependency: str,
    result_by_step: dict[str, StepResult],
    state: AgentState,
) -> bool:
    if dependency in state.completed_steps:
        return True
    result = result_by_step.get(dependency)
    return result is not None and result.ok


def _classify_tool_failure(tool_results: list[ToolResult]) -> str | None:
    for result in tool_results:
        if result.ok:
            continue
        if _is_approval_required(result):
            return "approval_required"
        audit = result.metadata.get("audit", {})
        audit_status = audit.get("status") if isinstance(audit, dict) else None
        content = result.content if isinstance(result.content, dict) else {}
        error = str(result.error or content.get("error") or "")
        if error.startswith("unknown tool:"):
            return "unknown_tool"
        if audit_status == "validation_failed":
            return "validation_failed"
        if "required_args" in content or "input_schema" in content:
            return "validation_failed"
        return "tool_runtime_error"
    return None
