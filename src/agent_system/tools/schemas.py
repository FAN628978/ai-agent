from __future__ import annotations

import json
from typing import Any, Literal

from pydantic import BaseModel, Field


class ToolPermission(BaseModel):
    filesystem: Literal["none", "read", "write"] = "none"
    shell: bool = False
    network: Literal["none", "restricted", "full"] = "none"
    approval_required: bool = False


class ToolPermissionPolicy(BaseModel):
    default_shell: Literal["allow", "ask", "deny"] = "allow"
    workspace_write: Literal["allow", "ask", "deny"] = "allow"
    network: Literal["allow", "ask", "deny"] = "allow"
    destructive_commands: Literal["allow", "ask", "deny"] = "allow"


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

    def required_arguments(self) -> list[str]:
        required = self.input_schema.get("required", [])
        if not isinstance(required, list):
            return []
        return [item for item in required if isinstance(item, str)]

    def optional_arguments(self) -> list[str]:
        properties = self.input_schema.get("properties", {})
        if not isinstance(properties, dict):
            return []
        required = set(self.required_arguments())
        return [name for name in properties if isinstance(name, str) and name not in required]

    def context_definition(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "risk": self.risk,
            "permission": self.permission.model_dump(mode="json"),
            "input_schema": self.input_schema,
            "required_arguments": self.required_arguments(),
            "optional_arguments": self.optional_arguments(),
        }

    def llm_tool_definition(self) -> dict[str, Any]:
        metadata = {
            "risk": self.risk,
            "permission": self.permission.model_dump(mode="json"),
            "required_arguments": self.required_arguments(),
            "optional_arguments": self.optional_arguments(),
        }
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": (
                    f"{self.description}\n"
                    f"Runtime metadata: {json.dumps(metadata, ensure_ascii=False, separators=(',', ':'))}"
                ),
                "parameters": self.input_schema,
            },
        }
