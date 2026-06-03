from agent_system.config import AppConfig
from agent_system.runtime import create_runtime_from_config


def test_create_runtime_from_config_uses_openai_compatible_planner() -> None:
    config = AppConfig()

    runtime = create_runtime_from_config(config)

    assert runtime.max_iterations == config.runtime.max_iterations
    assert runtime.planner.llm_client is not None
    assert runtime.planner.llm_client.base_url == "http://localhost:8500"
    assert runtime.planner.llm_client.model == "MiniMax-M2.5"
    assert runtime.executor.tool_router is not None
    assert any(tool.name == "file.read" for tool in runtime.planner.context.tools)
    assert any(skill.name == "runtime" for skill in runtime.planner.context.skills)
