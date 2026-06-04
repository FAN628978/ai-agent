from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_system.models import ToolCall, ToolResult
from agent_system.tools.base import ToolContext, Workspace
from agent_system.tools.registry import ToolRegistry
from agent_system.tools.schemas import ToolPermissionDecision, ToolPermissionPolicy


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
        try:
            tool = self.registry.get(call.name)
        except KeyError:
            return ToolResult(
                call_id=call.id,
                name=call.name,
                ok=False,
                content=None,
                error=f"unknown tool: {call.name}",
                metadata=_audit_metadata(call, status="error"),
            )

        ctx = ToolContext(call_id=call.id, workspace=self.workspace, permission_policy=self.permission_policy)
        try:
            validation = await tool.validate_input(call.arguments, ctx)
            if not validation.ok:
                return ToolResult(
                    call_id=call.id,
                    name=call.name,
                    ok=False,
                    content=None,
                    error=validation.message or "invalid tool input",
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
