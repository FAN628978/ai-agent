from __future__ import annotations

from pydantic import BaseModel, Field


class SkillSchema(BaseModel):
    name: str
    description: str
    triggers: list[str] = Field(default_factory=list)
    suggested_tools: list[str] = Field(default_factory=list)
    prompt_hints: list[str] = Field(default_factory=list)
    enabled: bool = True
