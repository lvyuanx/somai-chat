from somai_chat.api.websocket import _uploaded_image_urls


def test_uploaded_image_ids_resolve_to_server_loopback_urls() -> None:
    assert _uploaded_image_urls(["img_abc123"], 8000) == (
        "http://127.0.0.1:8000/api/v1/images/img_abc123",
    )
