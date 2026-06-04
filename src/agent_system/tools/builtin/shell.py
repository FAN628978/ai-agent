from __future__ import annotations

import asyncio

from agent_system.models import ToolResult
from agent_system.tools.base import BaseTool, ToolContext
from agent_system.tools.schemas import ToolPermission, ToolSchema


class BashTool(BaseTool):
    schema = ToolSchema(
        name="Bash",
        description="Run a shell command in the workspace.",
        input_schema={
            "type": "object",
            "properties": {
                "command": {"type": "string"},
                "timeout_s": {"type": "number", "default": 30},
            },
            "required": ["command"],
        },
        risk="high",
        permission=ToolPermission(filesystem="write", shell=True, approval_required=True),
        read_only=False,
        concurrency_safe=False,
    )

    def __init__(self, *, enabled: bool = False) -> None:
        self.enabled = enabled

    async def run(self, arguments: dict[str, object], ctx: ToolContext) -> ToolResult:
        if not self.enabled:
            return ToolResult(
                call_id=ctx.call_id,
                name=self.schema.name,
                ok=False,
                content=None,
                error="Bash is disabled",
            )

        command = str(arguments["command"])
        timeout_s = float(arguments.get("timeout_s", 30))
        process = await asyncio.create_subprocess_shell(
            command,
            cwd=str(ctx.workspace.root),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(process.communicate(), timeout=timeout_s)
        except TimeoutError:
            process.kill()
            await process.wait()
            return ToolResult(
                call_id=ctx.call_id,
                name=self.schema.name,
                ok=False,
                content=None,
                error=f"shell command timed out after {timeout_s:g}s",
            )

        stdout = stdout_bytes.decode("utf-8", errors="replace")
        stderr = stderr_bytes.decode("utf-8", errors="replace")
        return ToolResult(
            call_id=ctx.call_id,
            name=self.schema.name,
            ok=process.returncode == 0,
            content={"stdout": stdout, "stderr": stderr, "returncode": process.returncode},
            error=None if process.returncode == 0 else stderr,
        )
