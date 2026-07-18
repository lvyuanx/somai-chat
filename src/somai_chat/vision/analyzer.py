"""Provider-neutral image analysis for conversation runtime injection."""

import base64
from collections.abc import Sequence
from typing import Any, Protocol

from langchain_core.messages import AIMessage, HumanMessage


class ImageFetcher(Protocol):
    """Fetch a validated image as a media type and bytes."""

    async def fetch(self, url: str) -> tuple[str, bytes]: ...


class ImageAnalyzer(Protocol):
    """Describe supplied images as untrusted text for the chat model."""

    async def analyze(self, user_text: str, image_urls: Sequence[str]) -> str: ...


class VisionAnalyzer:
    """Turn image URLs into a bounded, data-only observation."""

    def __init__(self, fetcher: ImageFetcher, model: Any) -> None:
        self._fetcher = fetcher
        self._model = model

    async def analyze(self, user_text: str, image_urls: Sequence[str]) -> str:
        content: list[str | dict[str, object]] = [{"type": "text", "text": user_text}]
        for image_url in image_urls:
            media_type, data = await self._fetcher.fetch(image_url)
            encoded = base64.b64encode(data).decode("ascii")
            content.append({"type": "image_url", "image_url": {"url": f"data:{media_type};base64,{encoded}"}})
        response = await self._model.ainvoke([HumanMessage(content=content)])
        text = response.content if isinstance(response, AIMessage) else response
        if not isinstance(text, str) or not text.strip():
            raise ValueError("Vision model returned no text")
        return f"[UNTRUSTED_IMAGE_OBSERVATION]\n{text.strip()}\n[/UNTRUSTED_IMAGE_OBSERVATION]"
