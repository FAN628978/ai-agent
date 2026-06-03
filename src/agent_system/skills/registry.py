from __future__ import annotations

from agent_system.skills.base import BaseSkill
from agent_system.skills.schemas import SkillSchema


class SkillRegistry:
    def __init__(self) -> None:
        self._skills: dict[str, BaseSkill] = {}

    def register(self, skill: BaseSkill) -> None:
        if skill.schema.name in self._skills:
            raise ValueError(f"duplicate skill: {skill.schema.name}")
        self._skills[skill.schema.name] = skill

    def get(self, name: str) -> BaseSkill:
        return self._skills[name]

    def schemas(self, *, enabled_only: bool = True) -> list[SkillSchema]:
        schemas = [skill.schema for skill in self._skills.values()]
        if not enabled_only:
            return schemas
        return [schema for schema in schemas if schema.enabled]

    def match(self, query: str, *, limit: int | None = None) -> list[SkillSchema]:
        normalized = query.lower()
        matches: list[SkillSchema] = []
        for schema in self.schemas():
            triggers = [schema.name, *schema.triggers]
            if any(trigger.lower() in normalized for trigger in triggers):
                matches.append(schema)
                if limit is not None and len(matches) >= limit:
                    break
        return matches
