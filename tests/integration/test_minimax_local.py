import asyncio
import os

import pytest

from agent_system.llm import ChatMessage, OpenAICompatibleClient


@pytest.mark.skipif(
    os.getenv("AGENT_SYSTEM_RUN_LOCAL_LLM_TESTS") != "1",
    reason="set AGENT_SYSTEM_RUN_LOCAL_LLM_TESTS=1 to run local MiniMax smoke tests",
)
def test_local_minimax_chat_smoke() -> None:
    client = OpenAICompatibleClient(
        base_url=os.getenv("AGENT_SYSTEM_LLM_BASE_URL", "http://localhost:8500"),
        model=os.getenv("AGENT_SYSTEM_LLM_MODEL", "MiniMax-M2.5"),
        timeout_s=30,
    )

    models = asyncio.run(client.list_models())
    assert client.model in models

    response = asyncio.run(
        client.chat(
            [ChatMessage(role="user", content="只回复 OK")],
            max_tokens=32,
            temperature=0,
        )
    )

    assert response.content.strip()
