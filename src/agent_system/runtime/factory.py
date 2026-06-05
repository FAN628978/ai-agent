from __future__ import annotations

from agent_system.agents import AgentReasoner, PlannerAgent
from agent_system.config import AppConfig, load_config
from agent_system.context import ContextAssembler
from agent_system.execution import Executor
from agent_system.llm import OpenAICompatibleClient
from agent_system.observability import JsonlEventLogger
from agent_system.runtime.loop import AgentRuntime
from agent_system.skills.builtin import default_skill_registry
from agent_system.tools import ToolPermissionPolicy, ToolRegistry, ToolRouter
from agent_system.tools.builtin import BashTool, EditFileTool, GlobTool, GrepSearchTool, ReadFileTool, WriteFileTool


def create_runtime_from_config(config: AppConfig | None = None, workspace_root: str = ".") -> AgentRuntime:
    app_config = config or load_config()
    registry = ToolRegistry()
    registry.register(ReadFileTool())
    registry.register(WriteFileTool())
    registry.register(EditFileTool())
    registry.register(GrepSearchTool())
    registry.register(GlobTool())
    registry.register(BashTool(enabled=app_config.permissions.default_shell != "deny"))
    skills = default_skill_registry()
    context = ContextAssembler(tool_registry=registry, skills=skills.schemas(), workspace=workspace_root)

    if app_config.model.provider != "openai-compatible":
        raise ValueError(f"unsupported model provider: {app_config.model.provider}")
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
    reasoner_client = OpenAICompatibleClient(
        base_url=app_config.model.base_url,
        model=app_config.model.executor,
        api_key=app_config.model.api_key,
        timeout_s=app_config.model.timeout_s,
    )
    reasoner = AgentReasoner(
        llm_client=reasoner_client,
        tool_registry=registry,
        environment=context.environment,
        max_tokens=app_config.model.max_tokens,
        temperature=app_config.model.temperature,
    )

    permission_policy = ToolPermissionPolicy(
        default_shell=app_config.permissions.default_shell,
        workspace_write=app_config.permissions.workspace_write,
        network=app_config.permissions.network,
        destructive_commands=app_config.permissions.destructive_commands,
    )
    executor = Executor(tool_router=ToolRouter(registry, workspace_root, permission_policy=permission_policy))
    event_logger = None
    if app_config.logging.enabled:
        event_logger = JsonlEventLogger(
            path=app_config.logging.path,
            level=app_config.logging.level,
        )

    return AgentRuntime(
        planner=planner,
        executor=executor,
        reasoner=reasoner,
        event_logger=event_logger,
        max_iterations=app_config.runtime.max_iterations,
    )
