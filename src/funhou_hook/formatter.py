"""String formatting for funhou messages."""

from __future__ import annotations

import json

from .messages import ApprovalMessage, FunhouMessage, LogMessage, SummaryMessage


def format_message(message: FunhouMessage) -> str:
    """Render a single-line log entry suitable for tail -f."""

    if isinstance(message, LogMessage):
        return _format_log(message)
    if isinstance(message, SummaryMessage):
        return _format_summary(message)
    return _format_approval(message)


def _format_log(message: LogMessage) -> str:
    timestamp = message.timestamp.strftime("%H:%M:%S")
    icon = {
        "info": "INFO",
        "warning": "WARN",
        "danger": "DANG",
        "error": "ERROR",
    }[message.level]
    return f"{timestamp} [{icon}] {message.tool}: {message.message}"


def _format_summary(message: SummaryMessage) -> str:
    timestamp = message.timestamp.strftime("%H:%M:%S")
    return f"{timestamp} [SUMMARY] {message.message} | next={message.next}"


def _format_approval(message: ApprovalMessage) -> str:
    timestamp = message.timestamp.strftime("%H:%M:%S")
    details = json.dumps({"command": message.command, "reason": message.reason}, ensure_ascii=False)
    return f"{timestamp} [APPROVAL] {message.tool}: {details}"