from __future__ import annotations

import asyncio
import re

from agent_system.models import ToolResult
from agent_system.tools.base import BaseTool, ToolContext
from agent_system.tools.schemas import ToolPermission, ToolPermissionDecision, ToolSchema


DESTRUCTIVE_COMMAND_PATTERNS = [
    r"\brm\s+.*(-r|-rf|-fr)\b",
    r"\bdel\s+",
    r"\brmdir\s+",
    r"\bremove-item\b",
    r"\bformat\b",
    r"\bshutdown\b",
    r"\breboot\b",
    r"\bgit\s+reset\s+--hard\b",
    r"\bgit\s+clean\s+.*-f\b",
]


class BashTool(BaseTool):
    schema = ToolSchema(
        name="Bash",
        description="Run a shell command in the workspace when no safer file/search tool can satisfy the request. Required arguments: command. May be disabled, denied, or require approval by policy.",
        input_schema={
            "type": "object",
            "properties": {
                "command": {"type": "string"},
                "timeout_s": {"type": "number", "default": 30},
            },
            "required": ["command"],
        },
        risk="high",
        permission=ToolPermission(filesystem="write", shell=True, approval_required=False),
        read_only=False,
        concurrency_safe=False,
    )

    def __init__(self, *, enabled: bool = True) -> None:
        self.enabled = enabled

    async def check_permissions(self, arguments: dict[str, object], ctx: ToolContext) -> ToolPermissionDecision:
        command = str(arguments.get("command", ""))

        shell_decision = self._decision_for_policy(ctx.permission_policy.default_shell, "shell execution")
        if shell_decision.behavior != "allow":
            return shell_decision

        if _looks_destructive(command):
            return self._decision_for_policy(ctx.permission_policy.destructive_commands, "destructive shell command")

        return ToolPermissionDecision(behavior="allow", reason="shell command is allowed by policy")

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


def _looks_destructive(command: str) -> bool:
    normalized = command.lower()
    return any(re.search(pattern, normalized) for pattern in DESTRUCTIVE_COMMAND_PATTERNS)
