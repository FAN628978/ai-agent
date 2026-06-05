from __future__ import annotations

from agent_system.execution import ExecutionResult
from agent_system.models import AgentState, Critique, Plan, StepResult, UserRequest


class Reflector:
    async def evaluate(
        self,
        goal: str,
        plan: Plan,
        result: ExecutionResult,
        *,
        request: UserRequest | None = None,
        state: AgentState | None = None,
        session_context: str = "",
    ) -> Critique:
        del goal, request, session_context
        expected_steps = {step.id for step in plan.steps}
        completed_steps = set(state.completed_steps) if state is not None else set()
        step_results = _combined_step_results(result, state, expected_steps)
        completed_steps.update(step.step_id for step in step_results if step.ok)
        missing_steps = sorted(expected_steps - completed_steps)
        failed_summaries = [
            _step_issue_summary(step)
            for step in step_results
            if not step.ok
        ]
        error_types = {
            step.error_type
            for step in step_results
            if not step.ok and step.error_type is not None
        }
        has_blocked_step = any(step.status == "blocked" for step in step_results)

        if missing_steps or failed_summaries:
            missing_items: list[str] = []
            if missing_steps:
                missing_items.append(f"Missing completed steps: {', '.join(missing_steps)}")
            missing_items.extend(failed_summaries)
            reason = "The current execution has not satisfied all planned steps or success criteria."
            next_action = "retry"
            if has_blocked_step:
                reason = "The current execution has blocked steps that prevent the plan from completing."
                next_action = "replan"
            return Critique(
                done=False,
                confidence=0.4,
                reason=reason,
                missing_items=missing_items,
                suggested_next_action=_suggested_next_action(error_types, has_blocked_step),
                issues=missing_items,
                next_action=next_action,
            )

        if any(step.id.startswith("reasoning-step-") for step in plan.steps):
            return Critique(
                done=False,
                confidence=0.6,
                reason="The selected tool calls have produced observations; the Reasoner must decide whether they satisfy the original goal.",
                missing_items=["Final answer or next decision from Reasoner."],
                suggested_next_action="Ask the Reasoner to synthesize a final answer or choose another action.",
                issues=["Final answer or next decision from Reasoner."],
                next_action="retry",
            )

        return Critique(
            done=True,
            confidence=0.9,
            reason="Current tool results satisfy the plan success criteria.",
            missing_items=[],
            suggested_next_action="final",
            issues=[],
            next_action="finish",
        )


def _combined_step_results(
    result: ExecutionResult,
    state: AgentState | None,
    expected_steps: set[str],
) -> list[StepResult]:
    combined: dict[str, StepResult] = {}
    if state is not None:
        for step_result in state.step_results:
            if step_result.step_id in expected_steps:
                combined[step_result.step_id] = step_result
    for step_result in result.step_results:
        if step_result.step_id in expected_steps:
            combined[step_result.step_id] = step_result
    return list(combined.values())


def _step_issue_summary(step: StepResult) -> str:
    details = [f"status={step.status}"]
    if step.error_type:
        details.append(f"error_type={step.error_type}")
    return f"{step.step_id} [{', '.join(details)}]: {step.summary}"


def _suggested_next_action(error_types: set[str], has_blocked_step: bool) -> str:
    if {"unknown_tool", "validation_failed"} & error_types:
        return "Use the Reasoner to correct the tool name or arguments using registered tool definitions and schemas."
    if "no_executable_tool" in error_types:
        return "Use the Reasoner to choose suitable registered tools, or decide whether the request can be answered without tools."
    if has_blocked_step:
        return "Use the Reasoner to decide whether to replan around blocked dependencies or ask the user for clarification."
    return "Use the Reasoner to decide whether to call more tools, ask the user, or replan."
