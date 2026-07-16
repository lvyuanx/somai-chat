"""OpenAI-compatible chat model construction."""

from langchain_openai import ChatOpenAI

from somai_chat.core.config import Settings


def create_chat_model(settings: Settings) -> ChatOpenAI:
    """Build the configured streaming chat model without exposing its secret."""
    stream_usage = settings.openai_base_url.host == "api.openai.com"
    return ChatOpenAI(
        base_url=str(settings.openai_base_url),
        api_key=settings.openai_api_key,
        model=settings.openai_model,
        temperature=settings.model_temperature,
        max_completion_tokens=settings.model_max_tokens,
        timeout=settings.model_timeout_seconds,
        streaming=True,
        stream_usage=stream_usage,
    )
