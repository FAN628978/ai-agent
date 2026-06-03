from __future__ import annotations

from agent_system.models import AgentState


class InMemoryCheckpointStore:
    def __init__(self) -> None:
        self._states: dict[str, AgentState] = {}

    async def save(self, state: AgentState) -> None:
        self._states[state.task_id] = state.model_copy(deep=True)

    async def get(self, task_id: str) -> AgentState | None:
        state = self._states.get(task_id)
        if state is None:
            return None
        return state.model_copy(deep=True)
