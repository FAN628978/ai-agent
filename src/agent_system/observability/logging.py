from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from agent_system.models import AgentEvent, UserRequest


class JsonlEventLogger:
    def __init__(self, path: str | Path, level: str = "info") -> None:
        self.path = Path(path)
        self.level = level.lower()

    def log_event(self, event: AgentEvent, request: UserRequest, task_id: str | None = None) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "timestamp": _utc_timestamp(),
            "level": self.level,
            "event_type": event.type,
            "session_id": request.session_id,
            "task_id": task_id or event.data.get("task_id"),
            "user_id": request.user_id,
            "workspace_id": request.workspace_id,
            "data": summarize_event_data(event),
        }
        with self.path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")


def summarize_event_data(event: AgentEvent) -> dict[str, Any]:
    data = event.model_dump(mode="json")["data"]
    event_type = event.type

    if event_type == "plan.created":
        steps = data.get("steps", [])
        risks = data.get("risks", [])
        return {
            "goal": data.get("goal"),
            "mode": data.get("mode"),
            "step_count": len(steps) if isinstance(steps, list) else 0,
            "risk_count": len(risks) if isinstance(risks, list) else 0,
        }

    if event_type == "execution.completed":
        summary = dict(data)
        summary.pop("tool_results", None)
        return summary

    if event_type == "reflection.completed":
        issues = data.get("issues", [])
        return {
            "done": data.get("done"),
            "confidence": data.get("confidence"),
            "next_action": data.get("next_action"),
            "issue_count": len(issues) if isinstance(issues, list) else 0,
        }

    return data


def _utc_timestamp() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")
