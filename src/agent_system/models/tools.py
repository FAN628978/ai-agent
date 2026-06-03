from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ToolCall(BaseModel):
    id: str
    name: str
    arguments: dict[str, Any]
    timeout_s: float = 30
    requires_approval: bool = False


class ToolResult(BaseModel):
    call_id: str
    name: str
    ok: bool
    content: Any
    error: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
