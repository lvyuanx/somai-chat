"""FastAPI application composition root."""

import inspect
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from somai_chat.agent.graph import build_conversation_graph
from somai_chat.api.health import router as health_router
from somai_chat.api.websocket import router as websocket_router
from somai_chat.application.conversation import ConversationRuntime
from somai_chat.core.config import Settings, get_settings
from somai_chat.core.logging import configure_logging
from somai_chat.providers.llm import create_chat_model

logger = logging.getLogger(__name__)


async def _close_resource(resource: object | None) -> None:
    if resource is None:
        return
    close = getattr(resource, "aclose", None) or getattr(resource, "close", None)
    if close is None:
        return
    result = close()
    if inspect.isawaitable(result):
        await result


def create_app(settings: Settings | None = None, runtime: ConversationRuntime | None = None) -> FastAPI:
    """Create an app whose production dependencies are initialized during lifespan."""

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        owned_resource: object | None = None
        resolved_settings = settings
        resolved_runtime = runtime
        try:
            if resolved_settings is None:
                resolved_settings = get_settings()
            configure_logging(resolved_settings.log_level)
            if resolved_runtime is None:
                model = create_chat_model(resolved_settings)
                owned_resource = model
                resolved_runtime = ConversationRuntime(build_conversation_graph(model))
            application.state.settings = resolved_settings
            application.state.runtime = resolved_runtime
            application.state.ready = True
        except Exception:
            configure_logging("INFO")
            logger.error("application dependencies unavailable")
            application.state.settings = None
            application.state.runtime = None
            application.state.ready = False
        try:
            yield
        finally:
            try:
                await _close_resource(owned_resource)
            except Exception:
                logger.error("application resource shutdown failed")
            application.state.ready = False

    application = FastAPI(lifespan=lifespan)
    application.state.settings = settings
    application.state.runtime = runtime
    application.state.ready = settings is not None and runtime is not None
    application.include_router(health_router)
    application.include_router(websocket_router)
    return application


app = create_app()
