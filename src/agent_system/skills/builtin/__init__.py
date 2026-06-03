from __future__ import annotations

from agent_system.skills.base import BaseSkill
from agent_system.skills.registry import SkillRegistry
from agent_system.skills.schemas import SkillSchema


class CodingSkill(BaseSkill):
    schema = SkillSchema(
        name="coding",
        description="Plan and implement scoped code changes in the workspace.",
        triggers=["code", "implement", "fix", "开发", "实现", "修改", "代码"],
        suggested_tools=["file.read", "file.write", "grep.search", "shell.run"],
        prompt_hints=[
            "Prefer minimal scoped edits that follow existing project patterns.",
            "Run focused tests when code behavior changes.",
        ],
    )


class RuntimeSkill(BaseSkill):
    schema = SkillSchema(
        name="runtime",
        description="Work on the agent runtime loop, planning, execution, and CLI chat flow.",
        triggers=["runtime", "chat", "agent", "cli", "对话", "运行时"],
        suggested_tools=["file.read", "file.write", "grep.search", "shell.run"],
        prompt_hints=[
            "Keep runtime behavior observable through events and tests.",
            "Avoid coupling direct chat mode to runtime-only behavior.",
        ],
    )


class ReviewSkill(BaseSkill):
    schema = SkillSchema(
        name="review",
        description="Review code changes for defects, regressions, and missing verification.",
        triggers=["review", "test", "bug", "风险", "审查", "测试"],
        suggested_tools=["file.read", "grep.search", "shell.run"],
        prompt_hints=[
            "Prioritize concrete bugs and behavioral risks.",
            "Mention test gaps separately from confirmed defects.",
        ],
    )


def default_skill_registry() -> SkillRegistry:
    registry = SkillRegistry()
    registry.register(CodingSkill())
    registry.register(RuntimeSkill())
    registry.register(ReviewSkill())
    return registry
