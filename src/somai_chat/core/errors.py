from enum import StrEnum


class ErrorCode(StrEnum):
    INVALID_MESSAGE = "INVALID_MESSAGE"
    GENERATION_IN_PROGRESS = "GENERATION_IN_PROGRESS"
    CANCEL_NOT_FOUND = "CANCEL_NOT_FOUND"
    MODEL_UNAVAILABLE = "MODEL_UNAVAILABLE"
    GENERATION_FAILED = "GENERATION_FAILED"


class SomaiError(Exception):
    def __init__(self, code: ErrorCode, safe_message: str) -> None:
        self.code = code
        self.safe_message = safe_message
        super().__init__(safe_message)
