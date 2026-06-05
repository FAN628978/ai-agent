from __future__ import annotations

import json
from typing import Protocol

from agent_system.context import ContextAssembler
from agent_system.llm import ChatMessage
from agent_system.models import Plan, RunMode, Step, ToolCall, UserRequest


TOOL_NAME_ALIASES = {
    "read": "Read",
    "file.read": "Read",
    "write": "Write",
    "file.write": "Write",
    "edit": "Edit",
    "file.edit": "Edit",
    "grep": "Grep",
    "search": "Grep",
    "glob": "Glob",
    "dirlist": "Glob",
    "dir.list": "Glob",
    "directorylist": "Glob",
    "directory.list": "Glob",
    "listdir": "Glob",
    "list.dir": "Glob",
    "listfiles": "Glob",
    "list.files": "Glob",
    "filelist": "Glob",
    "file.list": "Glob",
    "findfiles": "Glob",
    "find.files": "Glob",
    "list": "Glob",
    "ls": "Glob",
    "bash": "Bash",
    "shell": "Bash",
    "command": "Bash",
}


class PlannerLLMClient(Protocol):
    async def chat(
        self,
        messages: list[ChatMessage],
        *,
        max_tokens: int = 512,
        temperature: float = 0.2,
        tools: list[dict[str, object]] | None = None,
    ) -> object: ...


class PlannerAgent:
    def __init__(
        self,
        llm_client: PlannerLLMClient | None = None,
        context: ContextAssembler | None = None,
        max_tokens: int = 1024,
        temperature: float = 0.2,
    ) -> None:
        self.llm_client = llm_client
        self.context = context or ContextAssembler()
        self.max_tokens = max_tokens
        self.temperature = temperature

    async def make_plan(self, request: UserRequest, session_context: str | None = None) -> Plan:
        if self.llm_client is None:
            raise RuntimeError("PlannerAgent requires an LLM client.")
        try:
            return await self._make_llm_plan(request, session_context=session_context)
        except Exception as exc:
            plan = self._make_rule_plan(request)
            plan.assumptions.append("LLM planner failed; using the built-in conservative fallback planner.")
            plan.risks.append(str(exc))
            return plan

    def _make_rule_plan(self, request: UserRequest) -> Plan:
        return Plan(
            task_goal=request.content,
            mode=request.mode,
            steps=[
                Step(
                    id="step-1",
                    title="Handle user request",
                    objective=request.content,
                    acceptance=["Request has been processed by the runtime."],
                )
            ],
            expected_outputs=["A response that addresses the user request."],
            constraints=["Use only available runtime tools and respect configured permissions."],
            success_criteria=["The user request has been answered or the runtime has identified missing information."],
            assumptions=["Using the built-in conservative fallback planner."],
            risks=[] if request.mode != RunMode.BACKGROUND else ["Background execution is not implemented yet."],
        )

    async def _make_llm_plan(self, request: UserRequest, session_context: str | None = None) -> Plan:
        assert self.llm_client is not None
        messages = self.context.planner_messages(request, session_context=session_context)
        response = await self.llm_client.chat(
            messages,
            max_tokens=self.max_tokens,
            temperature=self.temperature,
            tools=self.context.llm_tools(),
        )
        native_tool_calls = self._normalize_native_tool_calls(getattr(response, "tool_calls", []))
        if native_tool_calls:
            return self._plan_from_tool_calls(request, native_tool_calls)
        content = getattr(response, "content")
        try:
            data = self._normalize_plan_data(self._extract_plan_json_object(content))
        except (json.JSONDecodeError, ValueError):
            return await self._revise_llm_plan_for_tools(
                request=request,
                messages=messages,
                previous_content=content,
                reason="The previous response was not a valid JSON plan.",
            )
        data["mode"] = request.mode
        plan = Plan.model_validate(data)
        if not _plan_has_tool_intent(plan):
            plan = await self._revise_llm_plan_for_tools(
                request=request,
                messages=messages,
                previous_content=content,
                reason="The previous plan did not include suggested_tools or tool_calls.",
            )
        return plan

    async def _revise_llm_plan_for_tools(
        self,
        request: UserRequest,
        messages: list[ChatMessage],
        previous_content: str,
        reason: str,
    ) -> Plan:
        assert self.llm_client is not None
        repair_messages = [
            *messages,
            ChatMessage(role="assistant", content=previous_content),
            ChatMessage(
                role="user",
                content=(
                    f"{reason} "
                    "Review the user's request again. If the request needs filesystem, search, shell, "
                    "or workspace observation, return a revised JSON plan with concrete tool_calls. "
                    "Use the plan keys task_goal, steps, expected_outputs, constraints, success_criteria, assumptions, and risks. "
                    "Choose tool names and arguments only from the registered tool definitions and their input_schema. "
                    "Use each tool's description, required_arguments, and optional_arguments to decide whether it fits. "
                    "For named locations outside the workspace, ask for clarification instead of inventing access. "
                    "If no tool is needed, return a JSON plan with empty suggested_tools and tool_calls. "
                    f"Current user request:\n{request.content}"
                ),
            ),
        ]
        response = await self.llm_client.chat(
            repair_messages,
            max_tokens=self.max_tokens,
            temperature=self.temperature,
            tools=self.context.llm_tools(),
        )
        native_tool_calls = self._normalize_native_tool_calls(getattr(response, "tool_calls", []))
        if native_tool_calls:
            return self._plan_from_tool_calls(request, native_tool_calls)
        data = self._extract_plan_json_object(getattr(response, "content"))
        data = self._normalize_plan_data(data)
        data["mode"] = request.mode
        plan = Plan.model_validate(data)
        if not plan.steps:
            raise ValueError("LLM planner response must include at least one step.")
        return plan

    def _extract_plan_json_object(self, content: str) -> dict[str, object]:
        decoder = json.JSONDecoder()
        for index, char in enumerate(content):
            if char != "{":
                continue
            try:
                data, _end = decoder.raw_decode(content[index:])
            except json.JSONDecodeError:
                continue
            if isinstance(data, dict) and ("task_goal" in data or "goal" in data) and "steps" in data:
                return data
        raise ValueError("LLM planner response did not contain a JSON plan.")

    def _normalize_plan_data(self, data: dict[str, object]) -> dict[str, object]:
        normalized = dict(data)
        normalized["task_goal"] = str(normalized.get("task_goal") or normalized.get("goal", ""))
        normalized.pop("goal", None)
        normalized["expected_outputs"] = self._normalize_string_list(normalized.get("expected_outputs", []))
        normalized["constraints"] = self._normalize_string_list(normalized.get("constraints", []))
        normalized["success_criteria"] = self._normalize_string_list(normalized.get("success_criteria", []))
        normalized["assumptions"] = self._normalize_string_list(normalized.get("assumptions", []))
        normalized["risks"] = self._normalize_string_list(normalized.get("risks", []))

        steps = normalized.get("steps", [])
        if not isinstance(steps, list):
            normalized["steps"] = []
            return normalized

        normalized_steps: list[dict[str, object]] = []
        for index, step in enumerate(steps, start=1):
            if not isinstance(step, dict):
                continue
            normalized_step = dict(step)
            normalized_step["id"] = str(normalized_step.get("id", f"step-{index}"))
            normalized_step["title"] = str(normalized_step.get("title", f"Step {index}"))
            normalized_step["objective"] = str(normalized_step.get("objective", ""))
            normalized_step["depends_on"] = self._normalize_string_list(normalized_step.get("depends_on", []))
            normalized_step["suggested_tools"] = self._normalize_tool_names(
                normalized_step.get("suggested_tools", [])
            )
            normalized_step["tool_calls"] = self._normalize_tool_calls(
                normalized_step.get("tool_calls", []),
                step_id=str(normalized_step["id"]),
            )
            normalized_step["risk"] = self._normalize_risk(normalized_step.get("risk", "low"))
            normalized_step["acceptance"] = self._normalize_string_list(normalized_step.get("acceptance", []))
            normalized_steps.append(normalized_step)

        normalized["steps"] = normalized_steps
        return normalized

    def _normalize_string_list(self, value: object) -> list[str]:
        if value is None:
            return []
        if isinstance(value, list):
            return [self._stringify(item) for item in value]
        return [self._stringify(value)]

    def _normalize_tool_names(self, value: object) -> list[str]:
        names = self._normalize_string_list(value)
        normalized: list[str] = []
        for name in names:
            tool_name = self._normalize_tool_name(name)
            if tool_name and tool_name not in normalized:
                normalized.append(tool_name)
        return normalized

    def _normalize_risk(self, value: object) -> str:
        risk = str(value).lower()
        if risk in {"low", "medium", "high"}:
            return risk
        return "low"

    def _stringify(self, value: object) -> str:
        if isinstance(value, str):
            return value
        return json.dumps(value, ensure_ascii=False)

    def _normalize_tool_calls(self, value: object, step_id: str) -> list[dict[str, object]]:
        if value is None:
            return []
        calls = value if isinstance(value, list) else [value]
        normalized_calls: list[dict[str, object]] = []
        for index, call in enumerate(calls, start=1):
            if not isinstance(call, dict):
                continue
            name = self._normalize_tool_name(call.get("name") or call.get("tool") or "")
            if not name:
                continue
            arguments = call.get("arguments", call.get("params", {}))
            if not isinstance(arguments, dict):
                arguments = {}
            arguments = self._normalize_tool_arguments(name, arguments)
            normalized_calls.append(
                {
                    "id": str(call.get("id", f"{step_id}:{name}:{index}")),
                    "name": name,
                    "arguments": arguments,
                    "timeout_s": float(call.get("timeout_s", 30)),
                    "requires_approval": bool(call.get("requires_approval", False)),
                }
            )
        return normalized_calls

    def _normalize_tool_name(self, value: object) -> str:
        name = str(value).strip()
        if not name:
            return ""
        return TOOL_NAME_ALIASES.get(name.lower(), name)

    def _normalize_tool_arguments(self, name: str, arguments: dict[str, object]) -> dict[str, object]:
        normalized = dict(arguments)
        if name in {"Read", "Write", "Edit", "Grep", "Glob"} and "path" not in normalized:
            for alias in ("file_path", "filepath", "dir", "directory"):
                if alias in normalized:
                    normalized["path"] = normalized.pop(alias)
                    break
        if name == "Glob":
            normalized.setdefault("path", ".")
        if name == "Grep":
            normalized.setdefault("path", ".")
        return normalized

    def _normalize_native_tool_calls(self, value: object) -> list[ToolCall]:
        if not isinstance(value, list):
            return []
        calls: list[ToolCall] = []
        for index, raw_call in enumerate(value, start=1):
            if not isinstance(raw_call, dict):
                continue
            function = raw_call.get("function", {})
            if not isinstance(function, dict):
                function = {}
            name = self._normalize_tool_name(function.get("name") or raw_call.get("name") or "")
            if not name:
                continue
            arguments = function.get("arguments", raw_call.get("arguments", {}))
            if isinstance(arguments, str):
                try:
                    arguments = json.loads(arguments)
                except json.JSONDecodeError:
                    arguments = {}
            if not isinstance(arguments, dict):
                arguments = {}
            calls.append(
                ToolCall(
                    id=str(raw_call.get("id") or f"native:{name}:{index}"),
                    name=name,
                    arguments=self._normalize_tool_arguments(name, arguments),
                )
            )
        return calls

    def _plan_from_tool_calls(self, request: UserRequest, tool_calls: list[ToolCall]) -> Plan:
        return Plan(
            task_goal=request.content,
            mode=request.mode,
            steps=[
                Step(
                    id="step-1",
                    title="Execute selected tools",
                    objective=request.content,
                    suggested_tools=list(dict.fromkeys(call.name for call in tool_calls)),
                    tool_calls=tool_calls,
                    acceptance=["Selected tool calls have been executed and observed."],
                )
            ],
            expected_outputs=["Tool observations needed to answer the user request."],
            constraints=["Use only the native tool calls selected from registered tool definitions."],
            success_criteria=["Selected tool calls have executed successfully and produced usable observations."],
            assumptions=["Planner LLM selected native tool calls from registered tool definitions."],
        )


def _plan_has_tool_intent(plan: Plan) -> bool:
    return any(step.tool_calls or step.suggested_tools for step in plan.steps)
