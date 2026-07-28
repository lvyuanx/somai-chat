"""Versioned administrator API for managed runtime capabilities."""

from dataclasses import asdict
from typing import cast

from fastapi import APIRouter, HTTPException, Request

from somai_chat.admin.auth import require_admin, require_csrf
from somai_chat.capabilities.models import (
    CapabilityNotFoundError,
    CapabilitySecretUnavailableError,
    CapabilityUpdate,
    CapabilityValidationError,
    CapabilityView,
)
from somai_chat.capabilities.service import CapabilityService
from somai_chat.core.logging import get_logger

router = APIRouter(prefix="/api/v1/admin/capabilities", tags=["admin"])
logger = get_logger()


def _service(request: Request) -> CapabilityService:
    return cast(CapabilityService, request.app.state.capability_service)


def _response(view: CapabilityView) -> dict[str, object]:
    return cast(dict[str, object], asdict(view))


@router.get("")
async def list_capabilities(request: Request) -> list[dict[str, object]]:
    require_admin(request)
    views = await _service(request).list_views()
    logger.bind(capability_count=len(views)).info("管理员查看能力列表")
    return [_response(view) for view in views]


@router.put("/{capability}")
async def update_capability(request: Request, capability: str, payload: CapabilityUpdate) -> dict[str, object]:
    require_csrf(request)
    try:
        view = await _service(request).update(capability, payload)
    except CapabilityNotFoundError:
        raise HTTPException(status_code=404, detail="Capability not found") from None
    except CapabilityValidationError as error:
        raise HTTPException(status_code=422, detail=str(error)) from None
    logger.bind(capability=capability, enabled=view.enabled).info("管理员更新能力")
    return _response(view)


@router.post("/{capability}/api-key/reveal")
async def reveal_capability_api_key(request: Request, capability: str) -> dict[str, str]:
    require_csrf(request)
    try:
        api_key = await _service(request).reveal_api_key(capability)
    except (CapabilityNotFoundError, CapabilitySecretUnavailableError):
        raise HTTPException(status_code=404, detail="Capability API Key is unavailable") from None
    logger.bind(capability=capability).info("管理员查看能力 API Key")
    return {"api_key": api_key}
