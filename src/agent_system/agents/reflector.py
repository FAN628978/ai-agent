from __future__ import annotations

from agent_system.execution import ExecutionResult
from agent_system.models import AgentState, Critique, Plan, UserRequest


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
        completed_steps.update(step.step_id for step in result.step_results if step.ok)
        missing_steps = sorted(expected_steps - completed_steps)
        failed_summaries = [
            f"{step.step_id}: {step.summary}"
            for step in result.step_results
            if not step.ok
        ]

        if missing_steps or failed_summaries:
            missing_items: list[str] = []
            if missing_steps:
                missing_items.append(f"Missing completed steps: {', '.join(missing_steps)}")
            missing_items.extend(failed_summaries)
            return Critique(
                done=False,
                confidence=0.4,
                reason="The current execution has not satisfied all planned steps or success criteria.",
                missing_items=missing_items,
                suggested_next_action="Use the Reasoner to decide whether to call more tools, ask the user, or replan.",
                issues=missing_items,
                next_action="retry",
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
