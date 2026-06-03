from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class ToolPermission(BaseModel):
    filesystem: Literal["none", "read", "write"] = "none"
    shell: bool = False
    network: Literal["none", "restricted", "full"] = "none"
    approval_required: bool = False


class ToolSchema(BaseModel):
    name: str
    description: str
    input_schema: dict[str, Any] = Field(default_factory=dict)
    risk: Literal["low", "medium", "high"] = "low"
    permission: ToolPermission = Field(default_factory=ToolPermission)
    read_only: bool = True
    cache_ttl_s: int | None = None
