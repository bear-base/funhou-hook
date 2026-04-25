"""Logging primitives for notification, operational, debug, and state/audit logs."""

from __future__ import annotations

import logging
from collections.abc import Iterable
from datetime import datetime
from enum import StrEnum
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OPERATIONAL_LOG_PATH = PACKAGE_ROOT / "logs" / "operational.log"

_STANDARD_RECORD_KEYS = frozenset(logging.makeLogRecord({}).__dict__.keys())
_LOGGER_NAMES = {
    "notification": "funhou.notification",
    "operational": "funhou.operational",
    "debug": "funhou.debug",
    "state_audit": "funhou.state_audit",
}
_NULL_HANDLER_MARKER = "_funhou_null_handler"
_OPERATIONAL_HANDLER_MARKER = "_funhou_operational_handler"


class LogKind(StrEnum):
    """Supported log streams."""

    Notification = "notification"
    Operational = "operational"
    Debug = "debug"
    StateAudit = "state_audit"


class OperationalFormatter(logging.Formatter):
    """Render operational logs as a single line with sorted extra fields."""

    default_time_format = "%Y-%m-%d %H:%M:%S"

    def format(self, record: logging.LogRecord) -> str:
        timestamp = datetime.fromtimestamp(record.created).strftime(self.default_time_format)
        level = record.levelname
        message = record.getMessage()
        extras = self._format_extras(record)
        if extras:
            return f"{timestamp} [{level}] {message} {extras}"
        return f"{timestamp} [{level}] {message}"

    def _format_extras(self, record: logging.LogRecord) -> str:
        extras = {
            key: value
            for key, value in record.__dict__.items()
            if key not in _STANDARD_RECORD_KEYS and not key.startswith("_")
        }
        if not extras:
            return ""
        return " ".join(f"{key}={extras[key]!r}" for key in sorted(extras))


def initialize_logging(operational_path: Path | None = None) -> None:
    """Configure all supported loggers."""

    _configure_null_logger(LogKind.Notification)
    _configure_operational_logger(operational_path or DEFAULT_OPERATIONAL_LOG_PATH)
    _configure_null_logger(LogKind.Debug)
    _configure_null_logger(LogKind.StateAudit)


def get_logger(kind: LogKind) -> logging.Logger:
    """Return the logger for the requested log kind."""

    logger = logging.getLogger(_LOGGER_NAMES[kind.value])
    logger.propagate = False
    if kind is not LogKind.Operational and not _has_null_handler(logger.handlers):
        _attach_null_handler(logger)
    return logger


def _configure_null_logger(kind: LogKind) -> None:
    logger = get_logger(kind)
    logger.setLevel(logging.NOTSET)
    if not _has_null_handler(logger.handlers):
        _attach_null_handler(logger)


def _configure_operational_logger(path: Path) -> None:
    logger = get_logger(LogKind.Operational)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    path.parent.mkdir(parents=True, exist_ok=True)

    current_handler = _find_operational_handler(logger.handlers)
    if current_handler is not None and Path(current_handler.baseFilename) == path:
        return

    if current_handler is not None:
        logger.removeHandler(current_handler)
        current_handler.close()

    handler = logging.FileHandler(path, encoding="utf-8")
    handler.setLevel(logging.INFO)
    handler.setFormatter(OperationalFormatter())
    setattr(handler, _OPERATIONAL_HANDLER_MARKER, True)
    logger.addHandler(handler)


def _has_null_handler(handlers: Iterable[logging.Handler]) -> bool:
    return any(getattr(handler, _NULL_HANDLER_MARKER, False) for handler in handlers)


def _attach_null_handler(logger: logging.Logger) -> None:
    handler = logging.NullHandler()
    setattr(handler, _NULL_HANDLER_MARKER, True)
    logger.addHandler(handler)


def _find_operational_handler(
    handlers: Iterable[logging.Handler],
) -> logging.FileHandler | None:
    for handler in handlers:
        if getattr(handler, _OPERATIONAL_HANDLER_MARKER, False):
            return handler  # type: ignore[return-value]
    return None
