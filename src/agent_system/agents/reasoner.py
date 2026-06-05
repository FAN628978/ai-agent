from __future__ import annotations

import json
from pathlib import Path
from typing import Literal, Protocol, cast

from pydantic import BaseModel, Field

from agent_system.llm import ChatMessage
from agent_system.models import Critique, Plan, ToolCall, ToolResult, UserRequest
from agent_system.tools.registry import ToolRegistry
from agent_system.tools.schemas import ToolSchema


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


class ReasonerLLMClient(Protocol):
    async def chat(
        self,
        messages: list[ChatMessage],
        *,
        max_tokens: int = 512,
        temperature: float = 0.2,
        tools: list[dict[str, object]] | None = None,
    ) -> object:
        ...


class AgentAction(BaseModel):
    action: Literal["tool_calls", "ask_user", "replan", "final"] = "tool_calls"
    thought: str = ""
    tool_calls: list[ToolCall] = Field(default_factory=list)
    final_answer: str | None = None
    needs_user_input: list[str] = Field(default_factory=list)
    replan_reason: str | None = None

    def summary(self) -> dict[str, object]:
        return {
            "action": self.action,
            "thought": self.thought,
            "tool_call_count": len(self.tool_calls),
            "tool_calls": [call.model_dump(mode="json") for call in self.tool_calls],
            "has_final_answer": bool(self.final_answer),
            "needs_user_input": self.needs_user_input,
            "replan_reason": self.replan_reason,
        }


class AgentReasoner:
    def __init__(
        self,
        llm_client: ReasonerLLMClient,
        tools: list[ToolSchema] | None = None,
        tool_registry: ToolRegistry | None = None,
        environment: str | None = None,
        *,
        max_tokens: int = 1024,
        temperature: float = 0.2,
        max_observation_chars: int = 12000,
    ) -> None:
        self.llm_client = llm_client
        self.tools = tools or []
        self.tool_registry = tool_registry
        self.environment = environment or _environment_context(".")
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.max_observation_chars = max_observation_chars

    async def next_action(
        self,
        *,
        request: UserRequest,
        session_context: str,
        plan: Plan,
        critique: Critique | None = None,
        tool_results: list[ToolResult],
        iteration: int,
    ) -> AgentAction:
        messages = self._messages(
            request=request,
            session_context=session_context,
            plan=plan,
            critique=critique,
            tool_results=tool_results,
            iteration=iteration,
        )
        try:
            response = await self._chat(messages)
            native_tool_calls = self._normalize_native_tool_calls(
                getattr(response, "tool_calls", []),
                iteration=iteration,
            )
            if native_tool_calls:
                return AgentAction(
                    action="tool_calls",
                    thought="Model selected native tool calls from registered tool definitions.",
                    tool_calls=native_tool_calls,
                )
            content = getattr(response, "content")
            return self._normalize_action(self._extract_json_object(content), iteration=iteration)
        except Exception as exc:
            if "content" in locals():
                try:
                    return await self._repair_invalid_response(messages, content, iteration=iteration)
                except Exception as repair_exc:
                    return self._fallback_action(
                        request=request,
                        tool_results=tool_results,
                        iteration=iteration,
                        error=repair_exc,
                    )
            return self._fallback_action(request=request, tool_results=tool_results, iteration=iteration, error=exc)

    async def _repair_invalid_response(
        self,
        messages: list[ChatMessage],
        previous_content: str,
        *,
        iteration: int,
    ) -> AgentAction:
        repair_messages = [
            *messages,
            ChatMessage(role="assistant", content=previous_content),
            ChatMessage(
                role="user",
                content=(
                    "The previous response was not a valid JSON action. "
                    "Return exactly one JSON object with keys action, thought, tool_calls, final_answer, "
                    "needs_user_input, and replan_reason. "
                    "Set action to one of: tool_calls, ask_user, replan, final. "
                    "Use only registered tool names from the registered tool definitions. "
                    "Do not include markdown or explanatory text outside the JSON object."
                ),
            ),
        ]
        response = await self._chat(repair_messages)
        native_tool_calls = self._normalize_native_tool_calls(getattr(response, "tool_calls", []), iteration=iteration)
        if native_tool_calls:
            return AgentAction(
                action="tool_calls",
                thought="Model selected native tool calls from registered tool definitions.",
                tool_calls=native_tool_calls,
            )
        return self._normalize_action(self._extract_json_object(getattr(response, "content")), iteration=iteration)

    def _messages(
        self,
        *,
        request: UserRequest,
        session_context: str,
        plan: Plan,
        critique: Critique | None,
        tool_results: list[ToolResult],
        iteration: int,
    ) -> list[ChatMessage]:
        tool_schemas = json.dumps(
            self._tool_definitions(),
            ensure_ascii=False,
            indent=2,
        )
        return [
            ChatMessage(
                role="system",
                content=(
                    "You are the reasoning controller inside a local Agent Runtime. "
                    "Use the plan, Reflector critique, and tool observations to decide the next action. "
                    "Return exactly one JSON object and no markdown. "
                    "Set action to exactly one of: tool_calls, ask_user, replan, final. "
                    "Use only registered tool names from the registered tool definitions. "
                    "Never invent tool names. "
                    "If the user's request is solved, set action=final and final_answer to the user-facing answer. "
                    "If more workspace evidence is needed, set action=tool_calls and tool_calls to concrete calls using the registered tools. "
                    "If the plan is unsuitable, set action=replan and explain replan_reason. "
                    "If a tool result reports a validation or execution error, use that observation to revise the next tool call or ask the user. "
                    "For unknown-tool observations, choose a registered tool from available_tools. "
                    "For validation errors, fix the arguments according to required_args and input_schema. "
                    "Never return action=tool_calls with empty tool_calls. "
                    "If the request cannot be completed safely or needs clarification, set action=ask_user and needs_user_input. "
                    "Do not invent filesystem contents, command output, or tool results."
                ),
            ),
            ChatMessage(
                role="system",
                content=(
                    "Registered tool definitions from ToolRegistry:\n"
                    f"{tool_schemas}\n\n"
                    f"Environment:\n{self.environment}\n\n"
                    "Required JSON shape:\n"
                    '{"action":"tool_calls|ask_user|replan|final","thought":"brief reasoning summary",'
                    '"tool_calls":[{"id":"optional",'
                    '"name":"registered tool name","arguments":{}}],'
                    '"final_answer":"answer or null","needs_user_input":[],"replan_reason":"reason or null"}\n\n'
                    "Construct tool arguments from each tool's description, input_schema, required_arguments, and optional_arguments."
                ),
            ),
            ChatMessage(
                role="user",
                content=(
                    f"Iteration: {iteration}\n"
                    f"Session context:\n{session_context or '(none)'}\n\n"
                    f"Current user request:\n{request.content}\n\n"
                    f"Current plan:\n{plan.model_dump_json(indent=2)}\n\n"
                    f"Reflector critique:\n{critique.model_dump_json(indent=2) if critique else '(none)'}\n\n"
                    f"Tool observations:\n{self._tool_observation(tool_results)}"
                ),
            ),
        ]

    def _tool_observation(self, tool_results: list[ToolResult]) -> str:
        payload = json.dumps(
            [result.model_dump(mode="json") for result in tool_results],
            ensure_ascii=False,
            indent=2,
        )
        if len(payload) <= self.max_observation_chars:
            return payload
        return payload[: self.max_observation_chars] + "\n...[truncated]"

    def _tool_schemas(self) -> list[ToolSchema]:
        if self.tool_registry is not None:
            return self.tool_registry.schemas()
        return self.tools

    def _tool_definitions(self) -> list[dict[str, object]]:
        if self.tool_registry is not None:
            return self.tool_registry.definitions()
        return [tool.context_definition() for tool in self.tools]

    def _llm_tools(self) -> list[dict[str, object]]:
        if self.tool_registry is not None:
            return self.tool_registry.llm_tools()
        return [tool.llm_tool_definition() for tool in self.tools]

    def _extract_json_object(self, content: str) -> dict[str, object]:
        decoder = json.JSONDecoder()
        for index, char in enumerate(content):
            if char != "{":
                continue
            try:
                data, _end = decoder.raw_decode(content[index:])
            except json.JSONDecodeError:
                continue
            if isinstance(data, dict):
                return data
        raise ValueError("Reasoner response did not contain a JSON object.")

    async def _chat(self, messages: list[ChatMessage]) -> object:
        try:
            return await self.llm_client.chat(
                messages,
                max_tokens=self.max_tokens,
                temperature=self.temperature,
                tools=self._llm_tools(),
            )
        except TypeError as exc:
            if "tools" not in str(exc):
                raise
            return await self.llm_client.chat(
                messages,
                max_tokens=self.max_tokens,
                temperature=self.temperature,
            )

    def _normalize_action(self, data: dict[str, object], *, iteration: int) -> AgentAction:
        tool_calls = self._normalize_tool_calls(data.get("tool_calls", []), iteration=iteration)
        final_answer = data.get("final_answer")
        needs_user_input = data.get("needs_user_input", [])
        action = str(data.get("action") or "").strip().lower()
        replan_reason = data.get("replan_reason")
        if isinstance(needs_user_input, str):
            needs_user_input = [needs_user_input]
        if not isinstance(needs_user_input, list):
            needs_user_input = []
        if action not in {"tool_calls", "ask_user", "replan", "final"}:
            if final_answer:
                action = "final"
            elif needs_user_input:
                action = "ask_user"
            elif str(replan_reason or "").strip():
                action = "replan"
            else:
                action = "tool_calls"
        normalized_action = cast(Literal["tool_calls", "ask_user", "replan", "final"], action)
        return AgentAction(
            action=normalized_action,
            thought=str(data.get("thought", "")),
            tool_calls=tool_calls,
            final_answer=str(final_answer).strip() if final_answer is not None else None,
            needs_user_input=[str(item) for item in needs_user_input],
            replan_reason=str(replan_reason).strip() if replan_reason is not None else None,
        )

    def _normalize_tool_calls(self, value: object, *, iteration: int) -> list[ToolCall]:
        if not isinstance(value, list):
            return []

        calls: list[ToolCall] = []
        for index, raw_call in enumerate(value, start=1):
            if not isinstance(raw_call, dict):
                continue
            name = _normalize_tool_name(raw_call.get("name") or raw_call.get("tool") or "")
            if not name:
                continue
            arguments = raw_call.get("arguments", raw_call.get("params", {}))
            if not isinstance(arguments, dict):
                arguments = {}
            arguments = _normalize_tool_arguments(name, arguments)
            calls.append(
                ToolCall(
                    id=str(raw_call.get("id") or f"reason-{iteration}:{name}:{index}"),
                    name=name,
                    arguments=arguments,
                    requires_approval=bool(raw_call.get("requires_approval", False)),
                    approved=bool(raw_call.get("approved", False)),
                )
            )
        return calls

    def _normalize_native_tool_calls(self, value: object, *, iteration: int) -> list[ToolCall]:
        if not isinstance(value, list):
            return []

        calls: list[ToolCall] = []
        for index, raw_call in enumerate(value, start=1):
            if not isinstance(raw_call, dict):
                continue
            function = raw_call.get("function", {})
            if not isinstance(function, dict):
                function = {}
            name = _normalize_tool_name(function.get("name") or raw_call.get("name") or "")
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
            arguments = _normalize_tool_arguments(name, arguments)
            calls.append(
                ToolCall(
                    id=str(raw_call.get("id") or f"reason-{iteration}:{name}:{index}"),
                    name=name,
                    arguments=arguments,
                )
            )
        return calls

    def _fallback_action(
        self,
        *,
        request: UserRequest,
        tool_results: list[ToolResult],
        iteration: int,
        error: Exception,
    ) -> AgentAction:
        if not tool_results:
            return AgentAction(
                action="ask_user",
                thought=f"Reasoner LLM failed ({error}).",
                needs_user_input=["Reasoner could not produce a valid JSON next action."],
            )

        return AgentAction(
            action="final",
            thought=f"Reasoner LLM failed ({error}); summarize available observations.",
            final_answer=_fallback_answer(request, tool_results),
        )


def _normalize_tool_name(value: object) -> str:
    name = str(value).strip()
    if not name:
        return ""
    return TOOL_NAME_ALIASES.get(name.lower(), name)


def _normalize_tool_arguments(name: str, arguments: dict[str, object]) -> dict[str, object]:
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


def _fallback_answer(request: UserRequest, tool_results: list[ToolResult]) -> str:
    lines = [
        "已基于工具观察完成处理。LLM 后续推理输出不是合法 JSON，因此以下为 Runtime 的保守摘要。",
        f"用户请求：{request.content}",
    ]
    for result in tool_results:
        if result.name == "Glob" and isinstance(result.content, dict):
            lines.append(_glob_summary(result.content))
        elif result.name == "Grep" and isinstance(result.content, dict):
            lines.append(_grep_summary(result.content))
        elif result.name == "Read" and isinstance(result.content, dict):
            lines.append(_read_summary(result.content))
        elif not result.ok:
            lines.append(f"{result.name} 执行失败：{result.error}")
    return "\n".join(line for line in lines if line)


def _glob_summary(content: dict[str, object]) -> str:
    matches = content.get("matches", [])
    lines = [f"目录观察：{content.get('path')} 匹配 {content.get('pattern')}，共 {content.get('count', 0)} 项。"]
    if isinstance(matches, list):
        for entry in matches[:30]:
            if isinstance(entry, dict):
                marker = "/" if entry.get("type") == "directory" else ""
                lines.append(f"- {entry.get('relative_path') or entry.get('name')}{marker}")
    return "\n".join(lines)


def _grep_summary(content: dict[str, object]) -> str:
    matches = content.get("matches", [])
    lines = [f"文本搜索：找到 {content.get('count', 0)} 条相关匹配。"]
    if isinstance(matches, list):
        for match in matches[:20]:
            if isinstance(match, dict):
                lines.append(f"- {match.get('path')}:{match.get('line_number')}: {match.get('line')}")
    return "\n".join(lines)


def _read_summary(content: dict[str, object]) -> str:
    text = str(content.get("content", ""))
    return f"文件读取：{content.get('path')}\n{text[:2000]}"


def _environment_context(workspace: str) -> str:
    home = Path.home().resolve()
    return json.dumps(
        {
            "workspace": str(Path(workspace).resolve()),
            "home": str(home),
            "desktop": str(home / "Desktop"),
            "downloads": str(home / "Downloads"),
        },
        ensure_ascii=False,
        indent=2,
    )
