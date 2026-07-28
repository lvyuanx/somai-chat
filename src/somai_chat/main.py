"""FastAPI application composition root."""

import inspect
import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from ipaddress import ip_address
from pathlib import Path
from urllib.parse import urlsplit

import httpx
import uvicorn
from fastapi import FastAPI
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.middleware.sessions import SessionMiddleware
from starlette.requests import Request
from starlette.responses import Response

from somai_chat.admin.capability_repository import CapabilityRepository, MemoryCapabilityRepository
from somai_chat.admin.database import create_session_factory
from somai_chat.admin.presence import ClientPresenceRegistry
from somai_chat.admin.repository import ClientRepository
from somai_chat.agent.graph import build_conversation_graph
from somai_chat.api.admin import router as admin_router
from somai_chat.api.capabilities import router as capabilities_router
from somai_chat.api.health import router as health_router
from somai_chat.api.images import router as images_router
from somai_chat.api.websocket import router as websocket_router
from somai_chat.application.conversation import ConversationRuntime
from somai_chat.capabilities.models import CapabilitySeed
from somai_chat.capabilities.service import CapabilityService
from somai_chat.core.config import Settings, get_settings
from somai_chat.core.logging import configure_logging, get_logger
from somai_chat.device.tool import create_camera_capture_tool
from somai_chat.providers.llm import create_chat_model, create_vision_model, is_model_provider_unavailable
from somai_chat.vision.analyzer import VisionAnalyzer
from somai_chat.vision.fetcher import HttpImageFetcher

logger = get_logger()
WEB_DIRECTORY = Path(__file__).with_name("web")
ADMIN_WEB_DIRECTORY = Path(__file__).with_name("admin_web") / "dist"
_CSP_DOMAIN = re.compile(r"^[A-Za-z0-9.-]+$")


def _websocket_authority(request: Request) -> str | None:
    raw_host = request.headers.get("host", "")
    if not raw_host or any(ord(character) < 33 or ord(character) > 126 for character in raw_host):
        return None
    try:
        parsed = urlsplit(f"//{raw_host}")
        port = parsed.port
    except ValueError:
        return None
    host = parsed.hostname
    if host is None or parsed.username is not None or parsed.password is not None:
        return None
    if parsed.path or parsed.query or parsed.fragment:
        return None
    if ":" in host:
        try:
            host = f"[{ip_address(host).compressed}]"
        except ValueError:
            return None
    elif _CSP_DOMAIN.fullmatch(host) is None:
        return None
    return f"{host}:{port}" if port is not None else host


def _content_security_policy(request: Request) -> str:
    authority = _websocket_authority(request)
    connect_sources = "'self'" if authority is None else f"'self' ws://{authority} wss://{authority}"
    embedded_chat = request.url.path == "/assets/index.html" and request.query_params.get("embed") == "1"
    frame_ancestors = "'self'" if embedded_chat else "'none'"
    return (
        "default-src 'self'; img-src 'self' data:; script-src 'self'; style-src 'self'; "
        f"connect-src {connect_sources}; object-src 'none'; base-uri 'none'; frame-ancestors {frame_ancestors}"
    )


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Set browser security policy and prevent stale console assets."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        response = await call_next(request)
        response.headers["Content-Security-Policy"] = _content_security_policy(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        if request.url.path == "/" or request.url.path.startswith("/assets/"):
            response.headers["Cache-Control"] = "no-cache"
        return response


async def _close_resource(resource: object | None) -> None:
    if resource is None:
        return
    close = getattr(resource, "aclose", None) or getattr(resource, "close", None)
    if close is None:
        return
    result = close()
    if inspect.isawaitable(result):
        await result


def _capability_seeds(settings: Settings) -> list[CapabilitySeed]:
    return [
        CapabilitySeed(
            key="weather",
            enabled=settings.qweather_api_host is not None and settings.qweather_api_key is not None,
            configuration={
                "api_host": str(settings.qweather_api_host or "https://devapi.qweather.com"),
                "timeout_seconds": settings.weather_timeout_seconds,
            },
            api_key=settings.qweather_api_key.get_secret_value() if settings.qweather_api_key else None,
        ),
        CapabilitySeed(key="time", enabled=True, configuration={}, api_key=None),
        CapabilitySeed(
            key="web_search",
            enabled=settings.tavily_api_key is not None,
            configuration={
                "api_host": str(settings.tavily_api_host),
                "timeout_seconds": settings.tavily_timeout_seconds,
                "max_results": settings.tavily_max_results,
            },
            api_key=settings.tavily_api_key.get_secret_value() if settings.tavily_api_key else None,
        ),
    ]


def create_app(
    settings: Settings | None = None,
    runtime: ConversationRuntime | None = None,
    capability_service: CapabilityService | None = None,
) -> FastAPI:
    """Create an app whose production dependencies are initialized during lifespan."""

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        owned_resources: list[object] = []
        resolved_settings = settings
        resolved_runtime = runtime
        resolved_capability_service = capability_service
        try:
            if resolved_settings is None:
                resolved_settings = get_settings()
            configure_logging(resolved_settings.log_level, log_dir=resolved_settings.log_dir)
            logger.bind(
                environment=resolved_settings.environment,
                model=resolved_settings.openai_model,
                vision_enabled=resolved_settings.vision_model is not None,
                weather_enabled=resolved_settings.qweather_api_key is not None,
                search_enabled=resolved_settings.tavily_api_key is not None,
            ).info("应用启动开始")
            database_engine, sessions = create_session_factory(resolved_settings.database_connection_url())
            owned_resources.append(database_engine)
            application.state.client_repository = ClientRepository(
                sessions,
                resolved_settings.client_key_pepper.get_secret_value(),
                resolved_settings.client_key_encryption_secret.get_secret_value(),
            )
            if resolved_runtime is None:
                model = create_chat_model(resolved_settings)
                weather_http_client = httpx.AsyncClient(timeout=resolved_settings.weather_timeout_seconds)
                search_http_client = httpx.AsyncClient(timeout=resolved_settings.tavily_timeout_seconds)
                owned_resources.extend([model, weather_http_client, search_http_client])
                resolved_capability_service = CapabilityService(
                    (
                        MemoryCapabilityRepository()
                        if resolved_settings.environment == "test"
                        else CapabilityRepository(sessions)
                    ),
                    encryption_secret=resolved_settings.capability_secret_encryption_secret.get_secret_value(),
                    weather_http_client=weather_http_client,
                    search_http_client=search_http_client,
                )
                await resolved_capability_service.initialize(_capability_seeds(resolved_settings))
                image_analyzer = None
                if resolved_settings.vision_model is not None:
                    vision_http_client = httpx.AsyncClient(timeout=resolved_settings.vision_timeout_seconds)
                    owned_resources.append(vision_http_client)
                    image_analyzer = VisionAnalyzer(
                        HttpImageFetcher(vision_http_client, resolved_settings.max_image_download_bytes),
                        create_vision_model(resolved_settings),
                    )
                resolved_runtime = ConversationRuntime(
                    build_conversation_graph(
                        model,
                        tools=[create_camera_capture_tool()],
                        dynamic_tools=True,
                    ),
                    model_unavailable_classifier=is_model_provider_unavailable,
                    image_analyzer=image_analyzer,
                    tool_provider=resolved_capability_service,
                )
            application.state.settings = resolved_settings
            application.state.media_root = resolved_settings.media_root
            application.state.runtime = resolved_runtime
            application.state.capability_service = resolved_capability_service
            application.state.ready = True
            logger.bind(
                environment=resolved_settings.environment,
                vision_enabled=resolved_settings.vision_model is not None,
                weather_enabled=resolved_settings.qweather_api_key is not None,
                search_enabled=resolved_settings.tavily_api_key is not None,
            ).info("应用启动完成")
        except Exception:
            configure_logging(
                "INFO",
                log_dir=resolved_settings.log_dir if resolved_settings is not None else None,
            )
            logger.error("应用依赖不可用")
            application.state.settings = resolved_settings
            application.state.runtime = None
            application.state.ready = False
        try:
            yield
        finally:
            try:
                for resource in reversed(owned_resources):
                    await _close_resource(resource)
            except Exception:
                logger.error("应用资源关闭失败")
            application.state.ready = False
            logger.info("应用关闭完成")

    application = FastAPI(lifespan=lifespan)
    application.state.settings = settings
    application.state.media_root = settings.media_root if settings is not None else None
    application.state.runtime = runtime
    application.state.ready = settings is not None and runtime is not None
    application.state.client_repository = None
    application.state.capability_service = capability_service
    application.state.client_presence = ClientPresenceRegistry()
    application.add_middleware(
        SessionMiddleware,
        secret_key=(settings.admin_session_secret.get_secret_value() if settings is not None else "change-me"),
        https_only=settings is not None and settings.environment == "production",
        same_site="lax",
    )
    application.add_middleware(SecurityHeadersMiddleware)
    application.include_router(admin_router)
    application.include_router(capabilities_router)
    application.include_router(health_router)
    application.include_router(images_router)
    application.include_router(websocket_router)
    application.mount("/assets", StaticFiles(directory=WEB_DIRECTORY), name="assets")
    application.mount("/admin-assets", StaticFiles(directory=ADMIN_WEB_DIRECTORY), name="admin-assets")

    @application.get("/", include_in_schema=False)
    async def root() -> RedirectResponse:
        return RedirectResponse("/admin")

    @application.get("/admin", include_in_schema=False, response_class=FileResponse)
    async def admin_console() -> FileResponse:
        return FileResponse(ADMIN_WEB_DIRECTORY / "index.html")

    @application.get("/", include_in_schema=False, response_class=FileResponse)
    async def debug_console() -> FileResponse:
        return FileResponse(WEB_DIRECTORY / "index.html")

    return application


app = create_app()


def run() -> None:
    """Run Uvicorn with the same validated settings used by the application."""

    settings = get_settings()
    uvicorn.run(
        "somai_chat.main:app",
        host=settings.host,
        log_level="error",
        port=settings.port,
        reload=settings.environment == "development",
        ws_max_size=settings.websocket_transport_max_bytes,
    )


if __name__ == "__main__":
    run()
