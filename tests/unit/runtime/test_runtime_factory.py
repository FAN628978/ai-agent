import pytest

from agent_system.config import AppConfig, LoggingConfig, ModelConfig
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
        logging=LoggingConfig(enabled=False, path=str(path)),
    )

    runtime = create_runtime_from_config(config)

    assert runtime.event_logger is None
    assert not path.exists()


def test_create_runtime_from_config_rejects_unsupported_provider() -> None:
    config = AppConfig(model=ModelConfig(provider="rule"))

    with pytest.raises(ValueError, match="unsupported model provider"):
        create_runtime_from_config(config)
