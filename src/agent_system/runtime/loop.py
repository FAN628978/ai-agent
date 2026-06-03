from __future__ import annotations

from collections.abc import AsyncIterator
from uuid import uuid4

from agent_system.agents import PlannerAgent, Reflector
from agent_system.execution import Executor
from agent_system.models import AgentEvent, AgentState, RunMode, UserRequest
from agent_system.runtime.checkpoint import InMemoryCheckpointStore


class AgentRuntime:
    def __init__(
        self,
        planner: PlannerAgent | None = None,
        executor: Executor | None = None,
        reflector: Reflector | None = None,
        checkpoints: InMemoryCheckpointStore | None = None,
        max_iterations: int = 20,
    ) -> None:
        self.planner = planner or PlannerAgent()
        self.executor = executor or Executor()
        self.reflector = reflector or Reflector()
        self.checkpoints = checkpoints or InMemoryCheckpointStore()
        self.max_iterations = max_iterations

    async def run(self, request: UserRequest) -> AsyncIterator[AgentEvent]:
        state = AgentState(
            session_id=request.session_id,
            task_id=str(uuid4()),
            mode=request.mode,
            max_iterations=self.max_iterations,
        )

        yield AgentEvent(type="run.started", data={"task_id": state.task_id})

        while state.iteration < state.max_iterations:
            state.iteration += 1
            await self.checkpoints.save(state)

            if state.plan is None:
                state.plan = await self.planner.make_plan(request)
                yield AgentEvent(type="plan.created", data=state.plan.model_dump(mode="json"))

                if state.mode == RunMode.PLAN:
                    yield AgentEvent(type="run.waiting_for_approval", data={"task_id": state.task_id})
                    return

            execution = await self.executor.execute(state.plan, state)
            state.tool_results.extend(execution.tool_results)
            execution_data = execution.summary()
            execution_data["tool_results"] = [
                result.model_dump(mode="json") for result in execution.tool_results
            ]
            yield AgentEvent(type="execution.completed", data=execution_data)

            critique = await self.reflector.evaluate(
                goal=state.plan.goal,
                plan=state.plan,
                result=execution,
            )
            yield AgentEvent(type="reflection.completed", data=critique.model_dump(mode="json"))

            await self.checkpoints.save(state)

            if critique.done:
                yield AgentEvent(
                    type="run.completed",
                    data={"task_id": state.task_id, "confidence": critique.confidence},
                )
                return

            if critique.next_action == "ask_user":
                yield AgentEvent(type="run.needs_user_input", data={"issues": critique.issues})
                return

        yield AgentEvent(
            type="run.stopped",
            data={"reason": "max_iterations", "iterations": state.iteration},
        )
