from __future__ import annotations

import re

from agent_system.models import ToolResult
from agent_system.tools.base import BaseTool, ToolContext
from agent_system.tools.schemas import ToolPermission, ToolSchema


class GrepSearchTool(BaseTool):
    schema = ToolSchema(
        name="Grep",
        description="Search UTF-8 text files using a regular expression and return matching lines with paths and line numbers. Required arguments: pattern. Optional: path defaults to '.', max_results defaults to 100. Use this to locate relevant files or symbols.",
        input_schema={
            "type": "object",
            "properties": {
                "pattern": {"type": "string"},
                "path": {"type": "string", "default": "."},
                "max_results": {"type": "integer", "default": 100},
            },
            "required": ["pattern"],
        },
        risk="low",
        permission=ToolPermission(filesystem="read"),
        read_only=True,
    )

    async def run(self, arguments: dict[str, object], ctx: ToolContext) -> ToolResult:
        pattern = re.compile(str(arguments["pattern"]))
        root = ctx.workspace.resolve_read(str(arguments.get("path", ".")))
        max_results = int(arguments.get("max_results", 100))
        matches: list[dict[str, object]] = []

        files = [root] if root.is_file() else [path for path in root.rglob("*") if path.is_file()]
        for path in files:
            try:
                lines = path.read_text(encoding="utf-8").splitlines()
            except UnicodeDecodeError:
                continue
            for line_number, line in enumerate(lines, start=1):
                if pattern.search(line):
                    matches.append(
                        {
                            "path": str(path),
                            "line_number": line_number,
                            "line": line,
                        }
                    )
                    if len(matches) >= max_results:
                        return self._result(ctx.call_id, matches)

        return self._result(ctx.call_id, matches)

    def _result(self, call_id: str, matches: list[dict[str, object]]) -> ToolResult:
        return ToolResult(
            call_id=call_id,
            name=self.schema.name,
            ok=True,
            content={"matches": matches, "count": len(matches)},
        )
