from __future__ import annotations

from collections.abc import AsyncIterator
from uuid import uuid4

from agent_system.agents import PlannerAgent, Reflector
from agent_system.execution import Executor
from agent_system.models import AgentEvent, AgentState, RunMode, UserRequest
from agent_system.observability import JsonlEventLogger
from agent_system.runtime.checkpoint import InMemoryCheckpointStore
from agent_system.runtime.session import InMemorySessionStore, SessionRecord


class AgentRuntime:
    def __init__(
        self,
        planner: PlannerAgent | None = None,
        executor: Executor | None = None,
        reflector: Reflector | None = None,
        checkpoints: InMemoryCheckpointStore | None = None,
        session_store: InMemorySessionStore | None = None,
        event_logger: JsonlEventLogger | None = None,
        max_iterations: int = 20,
    ) -> None:
        self.planner = planner or PlannerAgent()
        self.executor = executor or Executor()
        self.reflector = reflector or Reflector()
        self.checkpoints = checkpoints or InMemoryCheckpointStore()
        self.session_store = session_store or InMemorySessionStore()
        self.event_logger = event_logger
        self.max_iterations = max_iterations

    async def run(self, request: UserRequest) -> AsyncIterator[AgentEvent]:
        session = await self.session_store.get(request.session_id)
        events: list[AgentEvent] = []
        state = AgentState(
            session_id=request.session_id,
            task_id=str(uuid4()),
            mode=request.mode,
            max_iterations=self.max_iterations,
        )

        event = AgentEvent(type="run.started", data={"task_id": state.task_id})
        events.append(event)
        self._log_event(event, request, state)
        yield event

        while state.iteration < state.max_iterations:
            state.iteration += 1
            await self.checkpoints.save(state)

            if state.plan is None:
                state.plan = await self.planner.make_plan(
                    request,
                    session_context=session.context_summary(),
                )
                event = AgentEvent(type="plan.created", data=state.plan.model_dump(mode="json"))
                events.append(event)
                self._log_event(event, request, state)
                yield event

                if state.mode == RunMode.PLAN:
                    event = AgentEvent(type="run.waiting_for_approval", data={"task_id": state.task_id})
                    events.append(event)
                    await self._save_session(session, request, state, events)
                    self._log_event(event, request, state)
                    yield event
                    return

            execution = await self.executor.execute(state.plan, state)
            state.tool_results.extend(execution.tool_results)
            execution_data = execution.summary()
            execution_data["tool_results"] = [
                result.model_dump(mode="json") for result in execution.tool_results
            ]
            event = AgentEvent(type="execution.completed", data=execution_data)
            events.append(event)
            self._log_event(event, request, state)
            yield event

            critique = await self.reflector.evaluate(
                goal=state.plan.goal,
                plan=state.plan,
                result=execution,
            )
            event = AgentEvent(type="reflection.completed", data=critique.model_dump(mode="json"))
            events.append(event)
            self._log_event(event, request, state)
            yield event

            await self.checkpoints.save(state)

            if critique.done:
                event = AgentEvent(
                    type="run.completed",
                    data={"task_id": state.task_id, "confidence": critique.confidence},
                )
                events.append(event)
                await self._save_session(session, request, state, events)
                self._log_event(event, request, state)
                yield event
                return

            if critique.next_action == "ask_user":
                event = AgentEvent(type="run.needs_user_input", data={"issues": critique.issues})
                events.append(event)
                await self._save_session(session, request, state, events)
                self._log_event(event, request, state)
                yield event
                return

        event = AgentEvent(
            type="run.stopped",
            data={"reason": "max_iterations", "iterations": state.iteration},
        )
        events.append(event)
        await self._save_session(session, request, state, events)
        self._log_event(event, request, state)
        yield event

    def _log_event(self, event: AgentEvent, request: UserRequest, state: AgentState) -> None:
        if self.event_logger is not None:
            self.event_logger.log_event(event, request, task_id=state.task_id)

    async def _save_session(
        self,
        session: SessionRecord,
        request: UserRequest,
        state: AgentState,
        events: list[AgentEvent],
    ) -> None:
        session.record_run(
            request=request,
            events=events,
            plan=state.plan,
            tool_results=state.tool_results,
        )
        await self.session_store.save(session)
