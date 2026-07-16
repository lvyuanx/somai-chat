import io
import json
import logging

from somai_chat.core.logging import configure_logging


def test_configure_logging_isolates_application_and_preserves_root() -> None:
    root = logging.getLogger()
    original_handlers = root.handlers[:]
    original_level = root.level
    root_stream = io.StringIO()
    root_handler = logging.StreamHandler(root_stream)
    root.handlers = [root_handler]
    app_stream = io.StringIO()
    app_logger = logging.getLogger("somai_chat.logging_isolation")
    original_app_handlers = app_logger.handlers[:]
    original_app_propagate = app_logger.propagate
    app_logger.handlers = []
    app_logger.propagate = True
    try:
        configure_logging("INFO", stream=app_stream)
        configure_logging("INFO", stream=app_stream)
        app_logger.info("fixed event", extra={"conversation_id": "conv_1"})
        for name in ("langchain", "langchain_openai", "openai", "httpx", "httpcore"):
            logging.getLogger(f"{name}.client").error("SECRET_DYNAMIC")

        lines = app_stream.getvalue().splitlines()
        assert len(lines) == 1
        assert json.loads(lines[0])["conversation_id"] == "conv_1"
        assert root.handlers == [root_handler]
        assert "SECRET_DYNAMIC" not in app_stream.getvalue()
        assert "SECRET_DYNAMIC" not in root_stream.getvalue()
    finally:
        app_logger.handlers = original_app_handlers
        app_logger.propagate = original_app_propagate
        root.handlers = original_handlers
        root.setLevel(original_level)
