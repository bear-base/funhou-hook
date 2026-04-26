"""Dispatch formatted messages to configured outputs."""

from __future__ import annotations

from codecs import BOM_UTF8
from pathlib import Path

from .config import SlackChannelConfig, TerminalChannelConfig
from .formatter import format_message
from .logging import LogKind, get_logger
from .messages import ApprovalMessage, FunhouMessage, LogMessage, SummaryMessage
from .slack_sender import SlackDeliveryError, send_slack_message


def dispatch_message(
    message: FunhouMessage,
    terminal: TerminalChannelConfig,
    slack: SlackChannelConfig | None = None,
) -> None:
    """Dispatch a message to the configured terminal and Slack channels."""

    if _should_deliver_to_terminal(message, terminal):
        _append_line(terminal.output, format_message(message))

    if slack is None or not slack.enabled:
        return

    if not _should_deliver_to_slack(message, slack):
        return

    try:
        send_slack_message(message, slack)
    except SlackDeliveryError as exc:
        get_logger(LogKind.Operational).error(
            "Slack delivery failed",
            extra={
                "channel": "slack",
                "event_type": message.type,
                "reason": str(exc),
            },
        )


def _should_deliver_to_terminal(message: FunhouMessage, channel: TerminalChannelConfig) -> bool:
    return _should_deliver(message, channel.message_types, channel.levels)


def _should_deliver_to_slack(message: FunhouMessage, channel: SlackChannelConfig) -> bool:
    return _should_deliver(message, channel.message_types, channel.levels)


def _should_deliver(
    message: FunhouMessage,
    message_types: tuple[str, ...],
    levels: tuple[str, ...],
) -> bool:
    if message.type not in message_types:
        return False

    if isinstance(message, SummaryMessage):
        return True

    if isinstance(message, LogMessage | ApprovalMessage):
        return message.level in levels

    return False


def _append_line(path: Path, line: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = f"{line}\n".encode()
    if not path.exists() or path.stat().st_size == 0:
        with path.open("wb") as handle:
            handle.write(BOM_UTF8)
            handle.write(payload)
        return

    with path.open("ab") as handle:
        handle.write(payload)
