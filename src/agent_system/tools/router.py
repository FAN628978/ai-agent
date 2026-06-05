from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_system.models import ToolCall, ToolResult
from agent_system.tools.base import ToolContext, Workspace
from agent_system.tools.registry import ToolRegistry
from agent_system.tools.schemas import ToolPermissionDecision, ToolPermissionPolicy


TOOL_NAME_ALIASES = {
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
    "ls": "Glob",
    "list": "Glob",
    "readfile": "Read",
    "file.read": "Read",
    "writefile": "Write",
    "file.write": "Write",
    "search": "Grep",
    "shell": "Bash",
    "bash": "Bash",
}


class ToolRouter:
    def __init__(
        self,
        registry: ToolRegistry,
        workspace_root: str | Path,
        permission_policy: ToolPermissionPolicy | None = None,
    ) -> None:
        self.registry = registry
        self.workspace = Workspace(workspace_root)
        self.permission_policy = permission_policy or ToolPermissionPolicy()

    async def invoke(self, call: ToolCall) -> ToolResult:
        call = _normalize_call(call)
        try:
            tool = self.registry.get(call.name)
        except KeyError:
            content = {
                "tool": call.name,
                "error": f"unknown tool: {call.name}",
                "available_tools": [tool["name"] for tool in _available_tools(self.registry)],
                "tool_definitions": _available_tools(self.registry),
                "hint": "Choose one of the available tools and generate valid arguments that match its schema.",
            }
            return ToolResult(
                call_id=call.id,
                name=call.name,
                ok=False,
                content=content,
                error=content["error"],
                metadata=_audit_metadata(call, status="error"),
            )

        ctx = ToolContext(call_id=call.id, workspace=self.workspace, permission_policy=self.permission_policy)
        try:
            validation = await tool.validate_input(call.arguments, ctx)
            if not validation.ok:
                content = {
                    "tool": call.name,
                    "error": validation.message or "invalid tool input",
                    "required_args": _required_args(tool.schema.input_schema),
                    "optional_args": tool.schema.optional_arguments(),
                    "input_schema": tool.schema.input_schema,
                    "schema": tool.schema.input_schema,
                    "tool_definition": tool.schema.context_definition(),
                    "available_tools": [tool["name"] for tool in _available_tools(self.registry)],
                    "tool_definitions": _available_tools(self.registry),
                    "hint": "Revise the tool call with arguments that satisfy the schema, or choose another available tool.",
                }
                return ToolResult(
                    call_id=call.id,
                    name=call.name,
                    ok=False,
                    content=content,
                    error=content["error"],
                    metadata=_audit_metadata(call, status="validation_failed"),
                )

            if call.requires_approval and not call.approved:
                decision = ToolPermissionDecision(
                    behavior="ask",
                    reason="tool call requires approval",
                )
                return ToolResult(
                    call_id=call.id,
                    name=call.name,
                    ok=False,
                    content={
                        "approval_required": True,
                        "tool": call.name,
                        "reason": decision.reason,
                        "arguments_summary": _summarize_arguments(call.arguments),
                    },
                    error="approval required",
                    metadata=_audit_metadata(call, status="approval_required", decision=decision),
                )

            decision = await tool.check_permissions(call.arguments, ctx)
            if decision.behavior == "deny":
                return ToolResult(
                    call_id=call.id,
                    name=call.name,
                    ok=False,
                    content=None,
                    error=decision.reason,
                    metadata=_audit_metadata(call, status="denied", decision=decision),
                )

            if decision.behavior == "ask" and not call.approved:
                return ToolResult(
                    call_id=call.id,
                    name=call.name,
                    ok=False,
                    content={
                        "approval_required": True,
                        "tool": call.name,
                        "reason": decision.reason,
                        "arguments_summary": _summarize_arguments(call.arguments),
                    },
                    error="approval required",
                    metadata=_audit_metadata(call, status="approval_required", decision=decision),
                )

            result = await tool.run(call.arguments, ctx)
            result.metadata.update(
                _audit_metadata(
                    call,
                    status="success" if result.ok else "error",
                    decision=decision,
                )
            )
            return result
        except Exception as exc:
            return ToolResult(
                call_id=call.id,
                name=call.name,
                ok=False,
                content=None,
                error=str(exc),
                metadata=_audit_metadata(call, status="error"),
            )


def _audit_metadata(
    call: ToolCall,
    *,
    status: str,
    decision: ToolPermissionDecision | None = None,
) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "audit": {
            "call_id": call.id,
            "tool": call.name,
            "arguments_summary": _summarize_arguments(call.arguments),
            "status": status,
        }
    }
    if decision is not None:
        metadata["permission"] = {
            "behavior": decision.behavior,
            "reason": decision.reason,
            **decision.metadata,
        }
    return metadata


def _summarize_arguments(arguments: dict[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for key, value in arguments.items():
        if isinstance(value, str):
            summary[key] = value if len(value) <= 120 else f"{value[:117]}..."
        elif isinstance(value, int | float | bool) or value is None:
            summary[key] = value
        else:
            summary[key] = type(value).__name__
    return summary


def _normalize_call(call: ToolCall) -> ToolCall:
    name = TOOL_NAME_ALIASES.get(call.name.strip().lower(), call.name)
    arguments = _normalize_arguments(name, call.arguments)
    if name == call.name and arguments == call.arguments:
        return call
    return call.model_copy(update={"name": name, "arguments": arguments})


def _normalize_arguments(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
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


def _available_tools(registry: ToolRegistry) -> list[dict[str, Any]]:
    return registry.definitions()


def _required_args(input_schema: dict[str, Any]) -> list[str]:
    required = input_schema.get("required", [])
    return [item for item in required if isinstance(item, str)] if isinstance(required, list) else []
