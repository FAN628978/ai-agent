from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class AgentEvent(BaseModel):
    type: str
    data: dict[str, Any] = Field(default_factory=dict)
