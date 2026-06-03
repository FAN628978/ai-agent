from __future__ import annotations

from agent_system.agents import PlannerAgent
from agent_system.config import AppConfig, load_config
from agent_system.context import ContextAssembler
from agent_system.execution import Executor
from agent_system.llm import OpenAICompatibleClient
from agent_system.runtime.loop import AgentRuntime
from agent_system.skills.builtin import default_skill_registry
from agent_system.tools import ToolRegistry, ToolRouter
from agent_system.tools.builtin import GrepSearchTool, ReadFileTool, ShellRunTool, WriteFileTool


def create_runtime_from_config(config: AppConfig | None = None, workspace_root: str = ".") -> AgentRuntime:
    app_config = config or load_config()
    planner = PlannerAgent()
    registry = ToolRegistry()
    registry.register(ReadFileTool())
    registry.register(WriteFileTool())
    registry.register(GrepSearchTool())
    registry.register(ShellRunTool(enabled=app_config.permissions.default_shell == "allow"))
    skills = default_skill_registry()
    context = ContextAssembler(tools=registry.schemas(), skills=skills.schemas(), workspace=workspace_root)

    if app_config.model.provider == "openai-compatible":
        llm_client = OpenAICompatibleClient(
            base_url=app_config.model.base_url,
            model=app_config.model.planner,
            api_key=app_config.model.api_key,
            timeout_s=app_config.model.timeout_s,
        )
        planner = PlannerAgent(
            llm_client=llm_client,
            context=context,
            max_tokens=app_config.model.max_tokens,
            temperature=app_config.model.temperature,
        )

    executor = Executor(tool_router=ToolRouter(registry, workspace_root))

    return AgentRuntime(
        planner=planner,
        executor=executor,
        max_iterations=app_config.runtime.max_iterations,
    )
