from collections.abc import Sequence

import pytest

from somai_chat.vision.analyzer import VisionAnalyzer


class FakeFetcher:
    async def fetch(self, url: str) -> tuple[str, bytes]:
        assert url == "http://images.example.test/cup.png"
        return "image/png", b"png-data"


class FakeModel:
    def __init__(self) -> None:
        self.messages: list[object] = []

    async def ainvoke(self, messages: Sequence[object]) -> str:
        self.messages = list(messages)
        return "A red cup."


@pytest.mark.asyncio
async def test_vision_analyzer_returns_untrusted_observation_from_qwen_content_blocks() -> None:
    model = FakeModel()
    analyzer = VisionAnalyzer(FakeFetcher(), model)

    observation = await analyzer.analyze("What is on the table?", ["http://images.example.test/cup.png"])

    assert observation == "[UNTRUSTED_IMAGE_OBSERVATION]\nA red cup.\n[/UNTRUSTED_IMAGE_OBSERVATION]"
    message = model.messages[0]
    assert message.content[0] == {"type": "text", "text": "What is on the table?"}
    assert message.content[1]["image_url"]["url"] == "data:image/png;base64,cG5nLWRhdGE="
