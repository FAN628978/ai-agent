from __future__ import annotations

from agent_system.skills.schemas import SkillSchema


class BaseSkill:
    schema: SkillSchema

    @property
    def name(self) -> str:
        return self.schema.name
