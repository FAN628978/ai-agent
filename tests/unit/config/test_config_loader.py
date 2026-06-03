from agent_system.config import load_config
from agent_system.models import RunMode


def test_load_default_config_includes_local_minimax() -> None:
    config = load_config()

    assert config.runtime.max_iterations == 20
    assert config.runtime.default_mode == RunMode.ACT
    assert config.model.provider == "openai-compatible"
    assert config.model.base_url == "http://localhost:8500"
    assert config.model.chat == "MiniMax-M2.5"
    assert config.model.planner == "MiniMax-M2.5"
    assert config.model.executor == "MiniMax-M2.5"
    assert config.model.reflector == "MiniMax-M2.5"
