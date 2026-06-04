from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from agent_system.models import ToolResult
from agent_system.tools.schemas import ToolPermissionDecision, ToolPermissionPolicy, ToolSchema, ToolValidationResult


class Workspace:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).resolve()

    def resolve(self, path: str | Path) -> Path:
        candidate = Path(path)
        if not candidate.is_absolute():
            candidate = self.root / candidate
        resolved = candidate.resolve()
        if not resolved.is_relative_to(self.root):
            raise ValueError(f"path escapes workspace: {path}")
        return resolved


class ToolContext(BaseModel):
    call_id: str
    workspace: Workspace
    permission_policy: ToolPermissionPolicy = Field(default_factory=ToolPermissionPolicy)

    model_config = {"arbitrary_types_allowed": True}


class BaseTool:
    schema: ToolSchema

    async def validate_input(self, arguments: dict[str, Any], ctx: ToolContext) -> ToolValidationResult:
        del ctx
        required = self.schema.input_schema.get("required", [])
        if isinstance(required, list):
            for key in required:
                if isinstance(key, str) and key not in arguments:
                    return ToolValidationResult(ok=False, message=f"missing required argument: {key}")
        return ToolValidationResult()

    async def check_permissions(self, arguments: dict[str, Any], ctx: ToolContext) -> ToolPermissionDecision:
        del arguments
        permission = self.schema.permission
        policy = ctx.permission_policy

        if permission.shell:
            decision = self._decision_for_policy(policy.default_shell, "shell execution")
            if decision.behavior != "allow":
                return decision

        if permission.network != "none":
            decision = self._decision_for_policy(policy.network, "network access")
            if decision.behavior != "allow":
                return decision

        if permission.filesystem == "write":
            decision = self._decision_for_policy(policy.workspace_write, "workspace write")
            if decision.behavior != "allow":
                return decision

        if self.schema.destructive:
            decision = self._decision_for_policy(policy.destructive_commands, "destructive operation")
            if decision.behavior != "allow":
                return decision

        if permission.approval_required or self.schema.risk == "high":
            return ToolPermissionDecision(behavior="ask", reason="tool requires approval")

        return ToolPermissionDecision(behavior="allow", reason="tool policy allows execution")

    def is_concurrency_safe(self, arguments: dict[str, Any]) -> bool:
        del arguments
        return self.schema.concurrency_safe

    def is_read_only(self, arguments: dict[str, Any]) -> bool:
        del arguments
        return self.schema.read_only

    def is_destructive(self, arguments: dict[str, Any]) -> bool:
        del arguments
        return self.schema.destructive

    async def run(self, arguments: dict[str, Any], ctx: ToolContext) -> ToolResult:
        raise NotImplementedError

    def _decision_for_policy(self, policy_value: str, capability: str) -> ToolPermissionDecision:
        if policy_value == "allow":
            return ToolPermissionDecision(behavior="allow", reason=f"{capability} is allowed by policy")
        if policy_value == "ask":
            return ToolPermissionDecision(behavior="ask", reason=f"{capability} requires approval by policy")
        return ToolPermissionDecision(behavior="deny", reason=f"{capability} is denied by policy")
