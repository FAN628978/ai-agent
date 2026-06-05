from __future__ import annotations

import json
from collections.abc import AsyncIterator
from uuid import uuid4

from agent_system.agents import AgentReasoner, PlannerAgent, Reflector
from agent_system.execution import Executor
from agent_system.models import AgentEvent, AgentState, Plan, RunMode, Step, ToolCall, ToolResult, UserRequest
from agent_system.observability import JsonlEventLogger
from agent_system.runtime.checkpoint import InMemoryCheckpointStore
from agent_system.runtime.session import InMemorySessionStore, SessionRecord


class AgentRuntime:
    def __init__(
        self,
        planner: PlannerAgent | None = None,
        executor: Executor | None = None,
        reflector: Reflector | None = None,
        reasoner: AgentReasoner | None = None,
        checkpoints: InMemoryCheckpointStore | None = None,
        session_store: InMemorySessionStore | None = None,
        event_logger: JsonlEventLogger | None = None,
        max_iterations: int = 20,
    ) -> None:
        if planner is None:
            raise ValueError("AgentRuntime requires a configured PlannerAgent.")
        self.planner = planner
        self.executor = executor or Executor()
        self.reflector = reflector or Reflector()
        self.reasoner = reasoner
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

        try:
            state.plan = await self.planner.make_plan(
                request,
                session_context=session.context_summary(),
            )
        except Exception as exc:
            event = AgentEvent(
                type="run.needs_user_input",
                data={
                    "issues": [f"Planner failed to produce a valid plan: {exc}"],
                },
            )
            events.append(event)
            await self._save_session(session, request, state, events)
            self._log_event(event, request, state)
            yield event
            return

        event = AgentEvent(type="plan.created", data=_plan_event_data(state.plan))
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

        while state.iteration < state.max_iterations:
            state.iteration += 1
            await self.checkpoints.save(state)

            execution = await self.executor.execute(state.plan, state)
            state.step_results.extend(execution.step_results)
            state.tool_results.extend(execution.tool_results)
            execution_data = execution.summary()
            execution_data["tool_results"] = [
                result.model_dump(mode="json") for result in execution.tool_results
            ]
            event = AgentEvent(type="execution.completed", data=execution_data)
            events.append(event)
            self._log_event(event, request, state)
            yield event

            approval_requests = _tool_approval_requests(execution.tool_results)
            if approval_requests:
                event = AgentEvent(
                    type="run.waiting_for_tool_approval",
                    data={
                        "task_id": state.task_id,
                        "tool_approvals": approval_requests,
                    },
                )
                events.append(event)
                await self._save_session(session, request, state, events)
                self._log_event(event, request, state)
                yield event
                return

            critique = await self.reflector.evaluate(
                goal=state.plan.goal,
                plan=state.plan,
                result=execution,
                request=request,
                state=state,
                session_context=session.context_summary(),
            )
            event = AgentEvent(type="reflection.completed", data=critique.model_dump(mode="json"))
            events.append(event)
            self._log_event(event, request, state)
            yield event

            await self.checkpoints.save(state)

            if critique.done:
                event = AgentEvent(
                    type="answer.created",
                    data={
                        "content": _final_answer_from_state(request, state, critique),
                        "source": "reflector",
                    },
                )
                events.append(event)
                self._log_event(event, request, state)
                yield event

                event = AgentEvent(
                    type="run.completed",
                    data={"task_id": state.task_id, "confidence": critique.confidence},
                )
                events.append(event)
                await self._save_session(session, request, state, events)
                self._log_event(event, request, state)
                yield event
                return

            if self.reasoner is None or state.mode != RunMode.ACT:
                event = AgentEvent(
                    type="run.needs_user_input",
                    data={"issues": critique.missing_items or critique.issues},
                )
                events.append(event)
                await self._save_session(session, request, state, events)
                self._log_event(event, request, state)
                yield event
                return

            if self.reasoner is not None and state.mode == RunMode.ACT:
                try:
                    action = await self.reasoner.next_action(
                        request=request,
                        session_context=session.context_summary(),
                        plan=state.plan,
                        critique=critique,
                        tool_results=state.tool_results,
                        step_results=state.step_results,
                        iteration=state.iteration,
                    )
                except Exception as exc:
                    event = AgentEvent(
                        type="run.needs_user_input",
                        data={"issues": [f"Reasoner failed to produce a valid next action: {exc}"]},
                    )
                    events.append(event)
                    await self._save_session(session, request, state, events)
                    self._log_event(event, request, state)
                    yield event
                    return

                event = AgentEvent(type="reasoning.completed", data=action.summary())
                events.append(event)
                self._log_event(event, request, state)
                yield event

                if action.action == "final" or action.final_answer:
                    event = AgentEvent(
                        type="answer.created",
                        data={
                            "content": action.final_answer or _final_answer_from_state(request, state, critique),
                            "source": "reasoner",
                        },
                    )
                    events.append(event)
                    self._log_event(event, request, state)
                    yield event

                    event = AgentEvent(
                        type="run.completed",
                        data={"task_id": state.task_id, "confidence": 0.9},
                    )
                    events.append(event)
                    await self._save_session(session, request, state, events)
                    self._log_event(event, request, state)
                    yield event
                    return

                if action.action == "ask_user" or action.needs_user_input:
                    issues = action.needs_user_input or critique.missing_items or critique.issues
                    event = AgentEvent(type="run.needs_user_input", data={"issues": issues})
                    events.append(event)
                    await self._save_session(session, request, state, events)
                    self._log_event(event, request, state)
                    yield event
                    return

                if action.action == "replan":
                    replan_context = (
                        f"{session.context_summary()}\n\n"
                        f"Reflector reason: {critique.reason}\n"
                        f"Missing items: {critique.missing_items}\n"
                        f"Reasoner replan reason: {action.replan_reason or action.thought}"
                    )
                    try:
                        state.plan = await self.planner.make_plan(request, session_context=replan_context)
                    except Exception as exc:
                        event = AgentEvent(
                            type="run.needs_user_input",
                            data={"issues": [f"Replanning failed to produce a valid plan: {exc}"]},
                        )
                        events.append(event)
                        await self._save_session(session, request, state, events)
                        self._log_event(event, request, state)
                        yield event
                        return
                    state.completed_steps.clear()
                    event = AgentEvent(type="plan.created", data=_plan_event_data(state.plan))
                    events.append(event)
                    self._log_event(event, request, state)
                    yield event
                    continue

                if action.action == "tool_calls" and action.tool_calls:
                    state.plan = _plan_from_tool_calls(request, state.iteration, action.tool_calls)
                    event = AgentEvent(type="plan.created", data=_plan_event_data(state.plan))
                    events.append(event)
                    self._log_event(event, request, state)
                    yield event
                    continue

                event = AgentEvent(
                    type="run.needs_user_input",
                    data={"issues": ["Reasoner returned no final answer and no tool calls."]},
                )
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


def _tool_approval_requests(tool_results: list[ToolResult]) -> list[dict[str, object]]:
    requests: list[dict[str, object]] = []
    for result in tool_results:
        content = result.content if isinstance(result.content, dict) else {}
        audit = result.metadata.get("audit", {})
        permission = result.metadata.get("permission", {})
        if not (
            content.get("approval_required") is True
            or (isinstance(audit, dict) and audit.get("status") == "approval_required")
        ):
            continue
        requests.append(
            {
                "call_id": result.call_id,
                "tool": content.get("tool") or result.name,
                "reason": content.get("reason") or _metadata_reason(permission) or result.error,
                "arguments_summary": content.get("arguments_summary")
                or _metadata_arguments_summary(audit),
            }
        )
    return requests


def _metadata_reason(permission: object) -> object:
    if isinstance(permission, dict):
        return permission.get("reason")
    return None


def _metadata_arguments_summary(audit: object) -> object:
    if isinstance(audit, dict):
        return audit.get("arguments_summary")
    return None


def _plan_from_tool_calls(request: UserRequest, iteration: int, tool_calls: list[ToolCall]) -> Plan:
    calls = list(tool_calls)
    return Plan(
        task_goal=request.content,
        mode=request.mode,
        steps=[
            Step(
                id=f"reasoning-step-{iteration}",
                title="Continue with selected tools",
                objective="Run the next tool calls selected from the previous observations.",
                suggested_tools=list(dict.fromkeys(call.name for call in calls)),
                tool_calls=calls,
                acceptance=["The selected tool calls have been executed and observed."],
            )
        ],
        expected_outputs=["A final answer based on the selected tool observations."],
        constraints=["Execute only the tool calls selected by the Reasoner."],
        success_criteria=["The selected tool calls produce enough evidence to answer the request."],
    )


def _plan_event_data(plan: Plan) -> dict[str, object]:
    data = plan.model_dump(mode="json")
    data["goal"] = plan.goal
    return data


def _final_answer_from_state(request: UserRequest, state: AgentState, critique: object) -> str:
    lines = [f"已完成：{request.content}"]
    reason = getattr(critique, "reason", "")
    if reason:
        lines.append(str(reason))
    if state.tool_results:
        lines.append("工具观察摘要：")
        for result in state.tool_results[-5:]:
            lines.append(_tool_result_answer_summary(result))
    return "\n".join(lines)


def _tool_result_answer_summary(result: ToolResult) -> str:
    if not result.ok:
        return f"- {result.name} 执行失败：{result.error}"
    if result.name == "Read" and isinstance(result.content, dict):
        path = result.content.get("path", "")
        text = str(result.content.get("content", ""))
        return f"- Read {path}\n{text[:2000]}"
    if result.name == "Glob" and isinstance(result.content, dict):
        matches = result.content.get("matches", [])
        paths: list[str] = []
        if isinstance(matches, list):
            for entry in matches[:50]:
                if isinstance(entry, dict):
                    marker = "/" if entry.get("type") == "directory" else ""
                    paths.append(f"{entry.get('relative_path') or entry.get('name')}{marker}")
        return _json_summary(
            {
                "tool": "Glob",
                "path": result.content.get("path"),
                "pattern": result.content.get("pattern"),
                "count": result.content.get("count"),
                "matches": paths,
            }
        )
    if result.name == "Grep" and isinstance(result.content, dict):
        return _json_summary(
            {
                "tool": "Grep",
                "count": result.content.get("count"),
                "matches": result.content.get("matches", [])[:20]
                if isinstance(result.content.get("matches"), list)
                else [],
            }
        )
    return f"- {result.name}: {_json_summary(result.content)}"


def _json_summary(value: object, max_chars: int = 2000) -> str:
    try:
        content = json.dumps(value, ensure_ascii=False, sort_keys=True)
    except TypeError:
        content = str(value)
    if len(content) <= max_chars:
        return content
    return content[:max_chars] + "...[truncated]"
