from __future__ import annotations

from pathlib import Path

from agent_system.models import ToolCall, ToolResult
from agent_system.tools.base import ToolContext, Workspace
from agent_system.tools.registry import ToolRegistry


class ToolRouter:
    def __init__(self, registry: ToolRegistry, workspace_root: str | Path) -> None:
        self.registry = registry
        self.workspace = Workspace(workspace_root)

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
            )

        ctx = ToolContext(call_id=call.id, workspace=self.workspace)
        try:
            return await tool.run(call.arguments, ctx)
        except Exception as exc:
            return ToolResult(
                call_id=call.id,
                name=call.name,
                ok=False,
                content=None,
                error=str(exc),
            )
