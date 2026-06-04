import asyncio

from agent_system.config import AppConfig, LoggingConfig, ModelConfig
from agent_system.models import UserRequest
from agent_system.runtime import create_runtime_from_config


def test_create_runtime_from_config_uses_openai_compatible_planner() -> None:
    config = AppConfig()

    runtime = create_runtime_from_config(config)

    assert runtime.max_iterations == config.runtime.max_iterations
    assert runtime.planner.llm_client is not None
    assert runtime.planner.llm_client.base_url == "http://localhost:8500"
    assert runtime.planner.llm_client.model == "MiniMax-M2.5"
    assert runtime.executor.tool_router is not None
    assert runtime.event_logger is not None
    assert any(tool.name == "Read" for tool in runtime.planner.context.tools)
    assert any(tool.name == "Edit" for tool in runtime.planner.context.tools)
    assert any(tool.name == "Glob" for tool in runtime.planner.context.tools)
    assert any(skill.name == "runtime" for skill in runtime.planner.context.skills)


def test_create_runtime_from_config_can_disable_event_logger(tmp_path) -> None:
    path = tmp_path / "events.jsonl"
    config = AppConfig(
        model=ModelConfig(provider="rule"),
        logging=LoggingConfig(enabled=False, path=str(path)),
    )

    runtime = create_runtime_from_config(config)
    request = UserRequest(
        session_id="session-1",
        user_id="user-1",
        workspace_id=str(tmp_path),
        content="Inspect project",
    )

    assert runtime.event_logger is None
    asyncio.run(_collect_events(runtime, request))
    assert not path.exists()


async def _collect_events(runtime, request):
    return [event async for event in runtime.run(request)]
