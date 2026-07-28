"""基于 loguru 统一配置项目日志和依赖日志的模块。"""

from __future__ import annotations

import json
import logging
import sys
from datetime import UTC, date, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, ClassVar, TextIO

from loguru import logger

from somai_chat.core.config import get_settings

if TYPE_CHECKING:
    from loguru import Record

PathLike = str | Path

CONSOLE_LEVEL_COLORS = {
    "TRACE": "<dim><cyan>",
    "DEBUG": "<cyan>",
    "INFO": "<green>",
    "SUCCESS": "<bold><green>",
    "WARNING": "<yellow>",
    "ERROR": "<red>",
    "CRITICAL": "<bold><red>",
}

_APPLICATION_LOGGER = "somai_chat"
_DEPENDENCY_LOGGERS = ("langchain", "langchain_openai", "openai", "httpx", "httpcore")
_CORRELATION_FIELDS = ("connection_id", "conversation_id", "message_id", "response_id", "error_code")
_SAFE_DETAIL_FIELDS = (
    "capability",
    "capability_count",
    "client_count",
    "client_id",
    "enabled",
    "environment",
    "event_type",
    "image_count",
    "model",
    "online_count",
    "reject_reason",
    "search_enabled",
    "vision_enabled",
    "weather_enabled",
)
_FIELD_LABELS = {
    "capability": "能力",
    "capability_count": "能力数",
    "client_count": "客户端数",
    "client_id": "客户端ID",
    "connection_id": "连接ID",
    "conversation_id": "会话ID",
    "enabled": "已启用",
    "environment": "环境",
    "error_code": "错误码",
    "event_type": "事件类型",
    "image_count": "图片数",
    "message_id": "消息ID",
    "model": "模型",
    "online_count": "在线数",
    "reject_reason": "拒绝原因",
    "response_id": "回复ID",
    "search_enabled": "搜索启用",
    "vision_enabled": "视觉启用",
    "weather_enabled": "天气启用",
}
_VALUE_LABELS = {
    "capability": {
        "time": "时间",
        "weather": "天气",
        "web_search": "联网搜索",
    },
    "environment": {
        "development": "开发",
        "production": "生产",
        "test": "测试",
    },
    "event_type": {
        "action.result": "动作结果",
        "message.create": "创建消息",
        "ping": "心跳",
        "response.cancel": "取消回复",
    },
    "reject_reason": {
        "invalid_client_key": "客户端 Key 无效",
        "invalid_conversation_id": "会话ID非法",
        "invalid_origin": "Origin 非法",
        "missing_authorization": "缺少认证",
        "origin_not_allowed": "Origin 未允许",
        "presence_unavailable": "在线状态服务不可用",
        "runtime_unavailable": "运行时不可用",
    },
}
_configured_key: tuple[Path, str, int] | None = None


class JsonFormatter(logging.Formatter):
    """Format stable application fields as one JSON object per record."""

    correlation_fields: ClassVar[tuple[str, ...]] = _CORRELATION_FIELDS

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat().replace("+00:00", "Z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for field in self.correlation_fields:
            value = getattr(record, field, None)
            if isinstance(value, str):
                payload[field] = value
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


class _InterceptHandler(logging.Handler):
    """将标准库 logging 记录转发到 loguru。"""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            level: str | int = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno

        extra: dict[str, object] = {"logger_name": record.name}
        if record.name == _APPLICATION_LOGGER or record.name.startswith(f"{_APPLICATION_LOGGER}."):
            extra["source"] = "project"
        for field in _CORRELATION_FIELDS:
            value = getattr(record, field, None)
            if isinstance(value, str):
                extra[field] = value

        logger.bind(**extra).opt(depth=6, exception=record.exc_info).log(level, record.getMessage())


def _apply_console_color_palette() -> None:
    """应用控制台日志使用的通用级别配色方案。"""
    for level_name, color in CONSOLE_LEVEL_COLORS.items():
        logger.level(level_name, color=color)


def _format_timestamp(record: Record) -> str:
    time = record["time"]
    return time.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]


def _logger_name(record: Record) -> str:
    extra = record["extra"]
    if isinstance(extra, dict):
        logger_name = extra.get("logger_name")
        if isinstance(logger_name, str):
            return logger_name
    return str(record["name"])


def _safe_correlation_suffix(record: Record) -> str:
    extra = record["extra"]
    if not isinstance(extra, dict):
        return ""
    parts = []
    for field in (*_CORRELATION_FIELDS, *_SAFE_DETAIL_FIELDS):
        value = extra.get(field)
        if isinstance(value, str | int | bool):
            label = _FIELD_LABELS.get(field, field)
            parts.append(f"{label}={_display_value(field, value)}")
    return "" if not parts else " | " + " | ".join(parts)


def _display_value(field: str, value: str | int | bool) -> str:
    if isinstance(value, bool):
        return "是" if value else "否"
    if isinstance(value, str):
        return _VALUE_LABELS.get(field, {}).get(value, value)
    return str(value)


def _plain_format(record: Record) -> str:
    return (
        f"{_format_timestamp(record)} | {record['level'].name:<8} | "
        f"{_logger_name(record)}:{record['function']}:{record['line']} | {record['message']}"
        f"{_safe_correlation_suffix(record)}\n"
    )


def _console_format(record: Record) -> str:
    return (
        f"<dim>{_format_timestamp(record)}</dim> | "
        f"<level>{record['level'].name:<8}</level> | "
        f"<cyan>{_logger_name(record)}</cyan>:<cyan>{record['function']}</cyan>:<cyan>{record['line']}</cyan> | "
        f"<level>{record['message']}</level>"
        f"{_safe_correlation_suffix(record)}\n"
    )


def _forward_standard_logging(level: str) -> None:
    handler = _InterceptHandler()
    stdlib_level = getattr(logging, level, logging.INFO)
    for name in (_APPLICATION_LOGGER, *_DEPENDENCY_LOGGERS):
        named_logger = logging.getLogger(name)
        named_logger.handlers = [handler]
        named_logger.setLevel(stdlib_level)
        named_logger.propagate = False


def configure_logging(level: str = "INFO", *, log_dir: PathLike | None = None, stream: TextIO | None = None) -> None:
    """配置全量、项目专属和错误日志输出。"""
    global _configured_key

    active_log_dir = Path(log_dir) if log_dir is not None else Path.cwd() / "logs"
    normalized_level = level.upper()
    target_stream = stream if stream is not None else sys.stdout
    configured_key = (active_log_dir.resolve(), normalized_level, id(target_stream))
    if _configured_key == configured_key:
        return

    active_log_dir.mkdir(parents=True, exist_ok=True)
    logger.remove()
    _apply_console_color_palette()

    today = date.today().isoformat()
    logger.add(active_log_dir / f"{today}-all.log", level=normalized_level, format=_plain_format, encoding="utf-8")
    logger.add(
        active_log_dir / f"{today}-project.log",
        level=normalized_level,
        format=_plain_format,
        encoding="utf-8",
        filter=lambda record: record["extra"].get("source") == "project",
    )
    logger.add(active_log_dir / f"{today}-error.log", level="ERROR", format=_plain_format, encoding="utf-8")
    logger.add(
        target_stream,
        level=normalized_level,
        format=_console_format,
        colorize=True,
        filter=lambda record: record["extra"].get("source") == "project",
    )
    _forward_standard_logging(normalized_level)
    _configured_key = configured_key


def setup_logging(
    log_dir: PathLike | None = None,
    log_level: str | None = None,
    *,
    stream: TextIO | None = None,
) -> None:
    """向后兼容的日志配置入口。"""
    if log_dir is None or log_level is None:
        settings = get_settings()
        if log_dir is None:
            log_dir = settings.log_dir
        if log_level is None:
            log_level = settings.log_level
    configure_logging(log_level, log_dir=log_dir, stream=stream)


def get_logger() -> Any:
    """获取带项目标记的 logger。"""
    return logger.bind(source="project")
