from __future__ import annotations

import json
from typing import Protocol

from agent_system.context import ContextAssembler
from agent_system.llm import ChatMessage
from agent_system.models import Plan, RunMode, Step, ToolCall, UserRequest


class PlannerLLMClient(Protocol):
    async def chat(
        self,
        messages: list[ChatMessage],
        *,
        max_tokens: int = 512,
        temperature: float = 0.2,
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

    async def make_plan(self, request: UserRequest) -> Plan:
        if self.llm_client is None:
            return self._make_rule_plan(request)

        try:
            return await self._make_llm_plan(request)
        except Exception as exc:
            plan = self._make_rule_plan(request)
            plan.assumptions = ["LLM planner failed; using the built-in rule-based planner."]
            plan.risks = [str(exc)]
            return plan

    def _make_rule_plan(self, request: UserRequest) -> Plan:
        return Plan(
            goal=request.content,
            mode=request.mode,
            steps=[
                Step(
                    id="step-1",
                    title="Handle user request",
                    objective=request.content,
                    suggested_tools=self._suggest_tools(request.content),
                    tool_calls=self._make_rule_tool_calls(request.content),
                    acceptance=["Request has been processed by the runtime."],
                )
            ],
            assumptions=["Using the built-in rule-based planner."],
            risks=[] if request.mode != RunMode.BACKGROUND else ["Background execution is not implemented yet."],
        )

    def _suggest_tools(self, content: str) -> list[str]:
        normalized = content.lower()
        if any(keyword in normalized for keyword in ["grep", "search", "find", "搜索", "查找"]):
            return ["grep.search"]
        if any(keyword in normalized for keyword in ["read", "open", "show", "cat", "读取", "打开", "查看"]):
            return ["file.read"]
        return []

    def _make_rule_tool_calls(self, content: str) -> list[ToolCall]:
        suggested_tools = self._suggest_tools(content)
        if suggested_tools == ["file.read"]:
            return [
                ToolCall(
                    id="step-1:file.read",
                    name="file.read",
                    arguments={"path": self._extract_path(content)},
                )
            ]
        if suggested_tools == ["grep.search"]:
            return [
                ToolCall(
                    id="step-1:grep.search",
                    name="grep.search",
                    arguments={
                        "pattern": self._extract_value(content, "pattern", default=content),
                        "path": self._extract_value(content, "path", default="."),
                    },
                )
            ]
        return []

    async def _make_llm_plan(self, request: UserRequest) -> Plan:
        assert self.llm_client is not None
        response = await self.llm_client.chat(
            self.context.planner_messages(request),
            max_tokens=self.max_tokens,
            temperature=self.temperature,
        )
        content = getattr(response, "content")
        data = self._extract_json_object(content)
        data = self._normalize_plan_data(data)
        data["mode"] = request.mode
        return Plan.model_validate(data)

    def _extract_json_object(self, content: str) -> dict[str, object]:
        start = content.find("{")
        end = content.rfind("}")
        if start < 0 or end < start:
            raise ValueError("LLM planner response did not contain a JSON object.")
        return json.loads(content[start : end + 1])

    def _normalize_plan_data(self, data: dict[str, object]) -> dict[str, object]:
        normalized = dict(data)
        normalized["goal"] = str(normalized.get("goal", ""))
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
            normalized_step["suggested_tools"] = self._normalize_string_list(
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
            name = str(call.get("name", ""))
            if not name:
                continue
            arguments = call.get("arguments", {})
            if not isinstance(arguments, dict):
                arguments = {}
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

    def _extract_path(self, content: str) -> str:
        explicit = self._extract_value(content, "path", default="")
        if explicit:
            return explicit
        for token in content.split():
            candidate = token.strip(".,;:()[]{}\"'")
            if "/" in candidate or "\\" in candidate or "." in candidate:
                return candidate
        return content

    def _extract_value(self, content: str, key: str, default: str) -> str:
        import re

        match = re.search(rf"{re.escape(key)}=([^\s]+)", content)
        if match:
            return match.group(1).strip("\"'")
        return default
