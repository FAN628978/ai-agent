import asyncio

from agent_system.llm import ChatMessage, OpenAICompatibleClient


def test_list_models_parses_openai_compatible_response() -> None:
    client = OpenAICompatibleClient(base_url="http://localhost:8500", model="MiniMax-M2.5")

    def fake_request(method: str, path: str, body: dict | None = None) -> dict:
        assert method == "GET"
        assert path == "/v1/models"
        assert body is None
        return {"data": [{"id": "MiniMax-M2.5"}, {"id": "other-model"}]}

    client._request = fake_request  # type: ignore[method-assign]

    assert asyncio.run(client.list_models()) == ["MiniMax-M2.5", "other-model"]


def test_chat_posts_messages_and_parses_content() -> None:
    client = OpenAICompatibleClient(base_url="http://localhost:8500/", model="MiniMax-M2.5")

    def fake_request(method: str, path: str, body: dict | None = None) -> dict:
        assert method == "POST"
        assert path == "/v1/chat/completions"
        assert body == {
            "model": "MiniMax-M2.5",
            "messages": [{"role": "user", "content": "hello"}],
            "max_tokens": 16,
            "temperature": 0,
        }
        return {
            "model": "MiniMax-M2.5",
            "choices": [{"message": {"content": "OK"}}],
        }

    client._request = fake_request  # type: ignore[method-assign]

    response = asyncio.run(
        client.chat(
            [ChatMessage(role="user", content="hello")],
            max_tokens=16,
            temperature=0,
        )
    )

    assert response.model == "MiniMax-M2.5"
    assert response.content == "OK"
    assert response.raw["choices"][0]["message"]["content"] == "OK"
