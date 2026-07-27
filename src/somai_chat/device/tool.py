"""Provider-neutral tools for requesting capabilities from a connected device."""

import json
import re
from typing import Literal
from uuid import uuid4

from langchain_core.tools import BaseTool, tool

_REQUEST_ID = re.compile(r"^cam_req_[A-Za-z0-9_-]{1,128}$")
_ACTION_KEY = "somai_action"


@tool("camera_capture")
async def request_camera_capture(
    camera: Literal["front", "back"] = "back",
    reason: str = "需要查看用户当前看到的内容",
) -> str:
    """Request one still image from the connected device camera.

    Use this only when the user's question requires current visual information
    and no image has already been supplied in the conversation.
    """

    clean_reason = reason.strip()[:200] or "需要查看用户当前看到的内容"
    return json.dumps(
        {
            _ACTION_KEY: "camera.capture",
            "request_id": f"cam_req_{uuid4().hex}",
            "camera": camera,
            "count": 1,
            "reason": clean_reason,
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )


def create_camera_capture_tool() -> BaseTool:
    """Create the camera request tool bound to the conversation model."""

    return request_camera_capture


def parse_camera_capture_result(content: object) -> dict[str, str | int] | None:
    """Parse a trusted camera tool result without accepting arbitrary content."""

    if not isinstance(content, str):
        return None
    try:
        payload = json.loads(content)
    except (TypeError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    if payload.get(_ACTION_KEY) != "camera.capture":
        return None
    request_id = payload.get("request_id")
    camera = payload.get("camera")
    count = payload.get("count")
    reason = payload.get("reason")
    if (
        not isinstance(request_id, str)
        or _REQUEST_ID.fullmatch(request_id) is None
        or camera not in {"front", "back"}
        or count != 1
        or not isinstance(reason, str)
    ):
        return None
    return {
        "action": "camera.capture",
        "request_id": request_id,
        "camera": camera,
        "count": count,
        "reason": reason,
    }
