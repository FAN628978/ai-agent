import pytest

from agent_system.skills import BaseSkill, SkillRegistry, SkillSchema
from agent_system.skills.builtin import default_skill_registry


class ExampleSkill(BaseSkill):
    schema = SkillSchema(
        name="example",
        description="Example skill.",
        triggers=["sample", "示例"],
        suggested_tools=["Read"],
        prompt_hints=["Use this skill for examples."],
    )


def test_skill_registry_registers_and_lists_schemas() -> None:
    registry = SkillRegistry()

    registry.register(ExampleSkill())

    assert registry.get("example").name == "example"
    assert registry.schemas()[0].suggested_tools == ["Read"]


def test_skill_registry_rejects_duplicates() -> None:
    registry = SkillRegistry()
    registry.register(ExampleSkill())

    with pytest.raises(ValueError, match="duplicate skill: example"):
        registry.register(ExampleSkill())


def test_skill_registry_matches_by_name_and_trigger() -> None:
    registry = SkillRegistry()
    registry.register(ExampleSkill())

    assert [skill.name for skill in registry.match("please use example")] == ["example"]
    assert [skill.name for skill in registry.match("做一个示例")] == ["example"]


def test_default_skill_registry_contains_runtime_skill() -> None:
    registry = default_skill_registry()

    matches = registry.match("继续 runtime chat 开发")

    assert "runtime" in {skill.name for skill in matches}
