from __future__ import annotations

from pathlib import Path

from agent_system.models import ToolResult
from agent_system.tools.base import BaseTool, ToolContext
from agent_system.tools.schemas import ToolPermission, ToolSchema


class GlobTool(BaseTool):
    schema = ToolSchema(
        name="Glob",
        description="Find workspace files or directories by path pattern.",
        input_schema={
            "type": "object",
            "properties": {
                "pattern": {"type": "string"},
                "path": {"type": "string", "default": "."},
                "max_results": {"type": "integer", "default": 200},
            },
            "required": ["pattern"],
        },
        risk="low",
        permission=ToolPermission(filesystem="read"),
        read_only=True,
    )

    async def run(self, arguments: dict[str, object], ctx: ToolContext) -> ToolResult:
        root = ctx.workspace.resolve(str(arguments.get("path", ".")))
        pattern = str(arguments["pattern"])
        max_results = int(arguments.get("max_results", 200))
        matches: list[dict[str, object]] = []

        for path in sorted(root.glob(pattern), key=_sort_key):
            resolved = path.resolve()
            if not resolved.is_relative_to(ctx.workspace.root):
                continue
            matches.append(_entry_info(resolved, ctx.workspace.root))
            if len(matches) >= max_results:
                break

        return ToolResult(
            call_id=ctx.call_id,
            name=self.schema.name,
            ok=True,
            content={
                "path": str(root),
                "pattern": pattern,
                "matches": matches,
                "count": len(matches),
                "truncated": len(matches) == max_results,
            },
        )


def _entry_info(path: Path, workspace_root: Path) -> dict[str, object]:
    return {
        "name": path.name,
        "path": str(path),
        "relative_path": path.relative_to(workspace_root).as_posix(),
        "type": "directory" if path.is_dir() else "file",
        "size": None if path.is_dir() else path.stat().st_size,
    }


def _sort_key(path: Path) -> tuple[int, str]:
    return (0 if path.is_dir() else 1, path.name.lower())
