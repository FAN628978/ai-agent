from __future__ import annotations

from agent_system.execution import ExecutionResult
from agent_system.models import Critique, Plan


class Reflector:
    async def evaluate(self, goal: str, plan: Plan, result: ExecutionResult) -> Critique:
        expected_steps = {step.id for step in plan.steps}
        completed_steps = {step.step_id for step in result.step_results if step.ok}
        missing_steps = sorted(expected_steps - completed_steps)

        if missing_steps:
            return Critique(
                done=False,
                confidence=0.4,
                issues=[f"Missing completed steps: {', '.join(missing_steps)}"],
                next_action="retry",
            )

        return Critique(done=True, confidence=0.9)
