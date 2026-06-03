from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from agent_system.config.models import AppConfig


def load_config(path: str | Path = "configs/default.yaml") -> AppConfig:
    config_path = Path(path)
    content = config_path.read_text(encoding="utf-8")
    data: dict[str, Any] = yaml.safe_load(content) or {}
    return AppConfig.model_validate(data)
