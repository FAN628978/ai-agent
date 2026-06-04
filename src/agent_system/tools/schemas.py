from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class ToolPermission(BaseModel):
    filesystem: Literal["none", "read", "write"] = "none"
    shell: bool = False
    network: Literal["none", "restricted", "full"] = "none"
    approval_required: bool = False


class ToolPermissionPolicy(BaseModel):
    default_shell: Literal["allow", "ask", "deny"] = "deny"
    workspace_write: Literal["allow", "ask", "deny"] = "allow"
    network: Literal["allow", "ask", "deny"] = "deny"
    destructive_commands: Literal["allow", "ask", "deny"] = "deny"


class ToolValidationResult(BaseModel):
    ok: bool = True
    message: str | None = None


class ToolPermissionDecision(BaseModel):
    behavior: Literal["allow", "ask", "deny"]
    reason: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class ToolSchema(BaseModel):
    name: str
    description: str
    input_schema: dict[str, Any] = Field(default_factory=dict)
    risk: Literal["low", "medium", "high"] = "low"
    permission: ToolPermission = Field(default_factory=ToolPermission)
    read_only: bool = True
    concurrency_safe: bool = True
    destructive: bool = False
    cache_ttl_s: int | None = None
