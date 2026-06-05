from __future__ import annotations

from typing import Any

from agent_system.tools.base import BaseTool
from agent_system.tools.schemas import ToolSchema


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, BaseTool] = {}

    def register(self, tool: BaseTool) -> None:
        if tool.schema.name in self._tools:
            raise ValueError(f"duplicate tool: {tool.schema.name}")
        self._tools[tool.schema.name] = tool

    def get(self, name: str) -> BaseTool:
        return self._tools[name]

    def schemas(self, *, read_only: bool | None = None) -> list[ToolSchema]:
        schemas = [tool.schema for tool in self._tools.values()]
        if read_only is None:
            return schemas
        return [schema for schema in schemas if schema.read_only is read_only]

    def definitions(self, *, read_only: bool | None = None) -> list[dict[str, Any]]:
        return [schema.context_definition() for schema in self.schemas(read_only=read_only)]

    def llm_tools(self, *, read_only: bool | None = None) -> list[dict[str, Any]]:
        return [schema.llm_tool_definition() for schema in self.schemas(read_only=read_only)]

    def names(self, *, read_only: bool | None = None) -> list[str]:
        return [schema.name for schema in self.schemas(read_only=read_only)]
