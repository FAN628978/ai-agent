from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from agent_system.models import RunMode


class RuntimeConfig(BaseModel):
    max_iterations: int = 20
    default_mode: RunMode = RunMode.ACT
    stream_events: bool = True


class ModelConfig(BaseModel):
    provider: str = "openai-compatible"
    base_url: str = "http://localhost:8500"
    chat: str = "MiniMax-M2.5"
    planner: str = "MiniMax-M2.5"
    executor: str = "MiniMax-M2.5"
    reflector: str = "MiniMax-M2.5"
    api_key: str | None = None
    timeout_s: float = 30
    max_tokens: int = 1024
    temperature: float = 0.2
    chat_history_limit: int = 20
    chat_system_prompt: str = "你是一个在本地 CLI 中运行的 AI 助手。请用简洁、直接、实用的中文回答用户。"


class ContextConfig(BaseModel):
    max_tokens: int = 180000
    memory_budget: int = 12000
    rag_budget: int = 40000
    history_budget: int = 30000
    tool_result_budget: int = 25000


class PermissionsConfig(BaseModel):
    default_shell: Literal["allow", "ask", "deny"] = "deny"
    workspace_write: Literal["allow", "ask", "deny"] = "allow"
    network: Literal["allow", "ask", "deny"] = "deny"
    destructive_commands: Literal["allow", "ask", "deny"] = "deny"


class MemoryConfig(BaseModel):
    enabled: bool = False
    auto_write: bool = False


class LoggingConfig(BaseModel):
    enabled: bool = True
    path: str = "logs/agent-system.jsonl"
    level: str = "info"


class AppConfig(BaseModel):
    runtime: RuntimeConfig = RuntimeConfig()
    model: ModelConfig = ModelConfig()
    context: ContextConfig = ContextConfig()
    permissions: PermissionsConfig = PermissionsConfig()
    memory: MemoryConfig = MemoryConfig()
    logging: LoggingConfig = LoggingConfig()
