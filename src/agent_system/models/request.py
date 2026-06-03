from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class RunMode(str, Enum):
    ASK = "ask"
    PLAN = "plan"
    ACT = "act"
    REVIEW = "review"
    BACKGROUND = "background"


class UserRequest(BaseModel):
    session_id: str
    user_id: str
    workspace_id: str
    content: str
    mode: RunMode = RunMode.ACT
    attachments: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
