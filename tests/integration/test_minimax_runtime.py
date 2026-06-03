import asyncio
import os

import pytest

from agent_system.models import RunMode, UserRequest
from agent_system.runtime import create_runtime_from_config


@pytest.mark.skipif(
    os.getenv("AGENT_SYSTEM_RUN_LOCAL_LLM_TESTS") != "1",
    reason="set AGENT_SYSTEM_RUN_LOCAL_LLM_TESTS=1 to run local MiniMax runtime tests",
)
def test_runtime_created_from_config_runs_plan_mode_with_local_minimax() -> None:
    runtime = create_runtime_from_config()
    request = UserRequest(
        session_id="session-1",
        user_id="user-1",
        workspace_id="workspace-1",
        content="为这个 AI Agent 项目生成一个下一步开发计划，只返回 JSON",
        mode=RunMode.PLAN,
    )

    events = asyncio.run(_collect_events(runtime, request))

    assert [event.type for event in events] == [
        "run.started",
        "plan.created",
        "run.waiting_for_approval",
    ]
    assert events[1].data["goal"]
    assert events[1].data["steps"]


async def _collect_events(runtime, request):
    return [event async for event in runtime.run(request)]
