from __future__ import annotations

import json

from pydantic import BaseModel, Field

from agent_system.models import AgentEvent, Plan, ToolResult, UserRequest

MAX_MESSAGES = 20
MAX_RECENT_EVENTS = 50
MAX_RECENT_TOOL_RESULTS = 20
MAX_CONTEXT_CHARS = 4000
MAX_SUMMARY_CHARS = 2000
MAX_TOOL_DETAIL_CHARS = 1200
MAX_TOOL_MATCHES = 50
MAX_READ_CONTENT_CHARS = 800


class SessionRecord(BaseModel):
    session_id: str
    messages: list[dict[str, str]] = Field(default_factory=list)
    recent_events: list[AgentEvent] = Field(default_factory=list)
    recent_tool_results: list[ToolResult] = Field(default_factory=list)
    recent_plan: Plan | None = None
    summary: str = ""

    def context_summary(self, max_chars: int = MAX_CONTEXT_CHARS) -> str:
        lines: list[str] = []
        if self.summary:
            lines.append(f"Conversation summary:\n{self.summary}")
        if self.recent_plan is not None:
            lines.append(_plan_summary(self.recent_plan))
        if self.recent_tool_results:
            lines.append("Recent tool results:")
            for result in self.recent_tool_results[-5:]:
                lines.append(f"- {_tool_result_summary(result)}")
        return _shorten("\n\n".join(lines), max_chars=max_chars)

    def record_run(
        self,
        request: UserRequest,
        events: list[AgentEvent],
        plan: Plan | None,
        tool_results: list[ToolResult],
    ) -> None:
        self.messages.append({"role": "user", "content": request.content})
        self.messages.append({"role": "assistant", "content": _assistant_summary(events, plan)})
        self.messages = self.messages[-MAX_MESSAGES:]
        self.recent_events = events[-MAX_RECENT_EVENTS:]
        self.recent_tool_results = tool_results[-MAX_RECENT_TOOL_RESULTS:]
        self.recent_plan = plan
        self.summary = _message_summary(self.messages)

    def record_display_turn(self, user_content: str, assistant_content: str) -> None:
        if (
            len(self.messages) >= 2
            and self.messages[-2].get("role") == "user"
            and self.messages[-2].get("content") == user_content
            and self.messages[-1].get("role") == "assistant"
        ):
            self.messages[-1]["content"] = assistant_content
        else:
            self.messages.append({"role": "user", "content": user_content})
            self.messages.append({"role": "assistant", "content": assistant_content})
        self.messages = self.messages[-MAX_MESSAGES:]
        self.summary = _message_summary(self.messages)


class InMemorySessionStore:
    def __init__(self) -> None:
        self._sessions: dict[str, SessionRecord] = {}

    async def get(self, session_id: str) -> SessionRecord:
        session = self._sessions.get(session_id)
        if session is None:
            return SessionRecord(session_id=session_id)
        return session.model_copy(deep=True)

    async def save(self, session: SessionRecord) -> None:
        self._sessions[session.session_id] = session.model_copy(deep=True)


def _assistant_summary(events: list[AgentEvent], plan: Plan | None) -> str:
    if any(event.type == "run.waiting_for_approval" for event in events):
        return f"Created a plan for: {plan.goal if plan else 'the request'}"
    tool_approval = next((event for event in events if event.type == "run.waiting_for_tool_approval"), None)
    if tool_approval is not None:
        approvals = tool_approval.data.get("tool_approvals", [])
        return f"Waiting for tool approval: {approvals}"
    if any(event.type == "run.completed" for event in events):
        return f"Completed: {plan.goal if plan else 'the request'}"
    needs_input = next((event for event in events if event.type == "run.needs_user_input"), None)
    if needs_input is not None:
        return f"Needs user input: {needs_input.data.get('issues', [])}"
    stopped = next((event for event in events if event.type == "run.stopped"), None)
    if stopped is not None:
        return f"Stopped: {stopped.data.get('reason', 'unknown')}"
    return "Runtime processed the request."


def _plan_summary(plan: Plan) -> str:
    lines = [f"Previous plan goal: {plan.goal}"]
    if plan.steps:
        lines.append("Previous plan steps:")
        for step in plan.steps[:5]:
            lines.append(f"- {step.id}: {step.title}")
    return "\n".join(lines)


def _tool_result_summary(result: ToolResult) -> str:
    status = "ok" if result.ok else "failed"
    detail = result.error or _tool_content_summary(result)
    return f"{result.name} call_id={result.call_id} status={status} detail={detail}"


def _tool_content_summary(result: ToolResult) -> str:
    if not isinstance(result.content, dict):
        return _json_summary(result.content)
    if result.name == "Glob":
        return _glob_content_summary(result.content)
    if result.name == "Read":
        return _read_content_summary(result.content)
    if result.name == "Grep":
        return _grep_content_summary(result.content)
    return _json_summary(result.content)


def _glob_content_summary(content: dict[str, object]) -> str:
    matches = content.get("matches", [])
    paths: list[str] = []
    if isinstance(matches, list):
        for entry in matches[:MAX_TOOL_MATCHES]:
            if isinstance(entry, dict):
                path = entry.get("relative_path") or entry.get("path") or entry.get("name")
                if path is not None:
                    paths.append(str(path))
    return _json_summary(
        {
            "path": content.get("path"),
            "pattern": content.get("pattern"),
            "count": content.get("count"),
            "matches": paths,
            "truncated": content.get("truncated") or len(paths) == MAX_TOOL_MATCHES,
        }
    )


def _read_content_summary(content: dict[str, object]) -> str:
    text = str(content.get("content", ""))
    return _json_summary(
        {
            "path": content.get("path"),
            "content_excerpt": _shorten(text, max_chars=MAX_READ_CONTENT_CHARS),
        }
    )


def _grep_content_summary(content: dict[str, object]) -> str:
    matches = content.get("matches", [])
    summarized_matches: list[dict[str, object]] = []
    if isinstance(matches, list):
        for match in matches[:MAX_TOOL_MATCHES]:
            if isinstance(match, dict):
                summarized_matches.append(
                    {
                        "path": match.get("path"),
                        "line_number": match.get("line_number"),
                        "line": match.get("line"),
                    }
                )
    return _json_summary(
        {
            "count": content.get("count"),
            "matches": summarized_matches,
            "truncated": content.get("truncated") or len(summarized_matches) == MAX_TOOL_MATCHES,
        }
    )


def _json_summary(value: object, max_chars: int = MAX_TOOL_DETAIL_CHARS) -> str:
    try:
        content = json.dumps(value, ensure_ascii=False, sort_keys=True)
    except TypeError:
        content = str(value)
    return _shorten(content, max_chars=max_chars)


def _message_summary(messages: list[dict[str, str]], max_chars: int = MAX_SUMMARY_CHARS) -> str:
    lines = [_message_line(message) for message in messages[-10:]]
    return _shorten("\n".join(lines), max_chars=max_chars)


def _message_line(message: dict[str, str]) -> str:
    role = message.get("role", "unknown")
    content = _shorten(message.get("content", ""), max_chars=300)
    return f"- {role}: {content}"


def _shorten(value: str, max_chars: int = MAX_TOOL_DETAIL_CHARS) -> str:
    if len(value) <= max_chars:
        return value
    return value[:max_chars] + "...[truncated]"
