from __future__ import annotations

from agent_system.models import ToolResult
from agent_system.tools.base import BaseTool, ToolContext
from agent_system.tools.schemas import ToolPermission, ToolSchema


class ReadFileTool(BaseTool):
    schema = ToolSchema(
        name="Read",
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
        name="Write",
        description="Create or overwrite a UTF-8 text file in the workspace.",
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


class EditFileTool(BaseTool):
    schema = ToolSchema(
        name="Edit",
        description="Edit a UTF-8 text file by replacing text.",
        input_schema={
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "old_string": {"type": "string"},
                "new_string": {"type": "string"},
                "replace_all": {"type": "boolean", "default": False},
            },
            "required": ["path", "old_string", "new_string"],
        },
        risk="medium",
        permission=ToolPermission(filesystem="write"),
        read_only=False,
    )

    async def run(self, arguments: dict[str, object], ctx: ToolContext) -> ToolResult:
        path = ctx.workspace.resolve(str(arguments["path"]))
        old_string = str(arguments["old_string"])
        new_string = str(arguments["new_string"])
        replace_all = bool(arguments.get("replace_all", False))

        if old_string == "":
            return ToolResult(
                call_id=ctx.call_id,
                name=self.schema.name,
                ok=False,
                content=None,
                error="old_string must not be empty",
            )

        content = path.read_text(encoding="utf-8")
        occurrences = content.count(old_string)
        if occurrences == 0:
            return ToolResult(
                call_id=ctx.call_id,
                name=self.schema.name,
                ok=False,
                content=None,
                error="old_string not found",
            )
        if occurrences > 1 and not replace_all:
            return ToolResult(
                call_id=ctx.call_id,
                name=self.schema.name,
                ok=False,
                content=None,
                error="old_string appears multiple times; set replace_all=true to replace all occurrences",
            )

        updated = content.replace(old_string, new_string) if replace_all else content.replace(old_string, new_string, 1)
        path.write_text(updated, encoding="utf-8")
        replacements = occurrences if replace_all else 1
        return ToolResult(
            call_id=ctx.call_id,
            name=self.schema.name,
            ok=True,
            content={
                "path": str(path),
                "replacements": replacements,
                "bytes_written": len(updated.encode("utf-8")),
            },
        )
