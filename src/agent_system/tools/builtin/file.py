from __future__ import annotations

from agent_system.models import ToolResult
from agent_system.tools.base import BaseTool, ToolContext
from agent_system.tools.schemas import ToolPermission, ToolSchema


class ReadFileTool(BaseTool):
    schema = ToolSchema(
        name="file.read",
        description="Read a UTF-8 text file from the workspace.",
        input_schema={
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "max_bytes": {"type": "integer", "default": 20000},
            },
            "required": ["path"],
        },
        risk="low",
        permission=ToolPermission(filesystem="read"),
        read_only=True,
    )

    async def run(self, arguments: dict[str, object], ctx: ToolContext) -> ToolResult:
        path = ctx.workspace.resolve(str(arguments["path"]))
        max_bytes = int(arguments.get("max_bytes", 20000))
        content = path.read_text(encoding="utf-8")[:max_bytes]
        return ToolResult(
            call_id=ctx.call_id,
            name=self.schema.name,
            ok=True,
            content={"path": str(path), "content": content},
        )


class WriteFileTool(BaseTool):
    schema = ToolSchema(
        name="file.write",
        description="Write UTF-8 text to a workspace file.",
        input_schema={
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "content": {"type": "string"},
            },
            "required": ["path", "content"],
        },
        risk="medium",
        permission=ToolPermission(filesystem="write"),
        read_only=False,
    )

    async def run(self, arguments: dict[str, object], ctx: ToolContext) -> ToolResult:
        path = ctx.workspace.resolve(str(arguments["path"]))
        content = str(arguments["content"])
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return ToolResult(
            call_id=ctx.call_id,
            name=self.schema.name,
            ok=True,
            content={"path": str(path), "bytes_written": len(content.encode("utf-8"))},
        )
