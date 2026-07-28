import json

import pytest

from somai_chat.device.tool import create_camera_capture_tool, parse_camera_capture_result


@pytest.mark.asyncio
async def test_camera_capture_tool_returns_bounded_action_request() -> None:
    result = await create_camera_capture_tool().ainvoke({"camera": "back", "reason": "查看我手里的物体"})

    action = json.loads(result)
    assert action["somai_action"] == "camera.capture"
    assert action["camera"] == "back"
    assert action["count"] == 1
    assert action["request_id"].startswith("cam_req_")


def test_parse_camera_capture_result_rejects_untrusted_shape() -> None:
    assert parse_camera_capture_result("not-json") is None
    assert parse_camera_capture_result('{"somai_action":"other"}') is None
    assert (
        parse_camera_capture_result(
            '{"somai_action":"camera.capture","request_id":"bad","camera":"back","count":1,"reason":"拍照"}'
        )
        is None
    )
