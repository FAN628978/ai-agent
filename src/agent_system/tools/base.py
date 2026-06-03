from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel

from agent_system.models import ToolResult
from agent_system.tools.schemas import ToolSchema


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

    model_config = {"arbitrary_types_allowed": True}


class BaseTool:
    schema: ToolSchema

    async def run(self, arguments: dict[str, Any], ctx: ToolContext) -> ToolResult:
        raise NotImplementedError
