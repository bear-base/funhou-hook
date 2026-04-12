"""Dispatch formatted messages to configured outputs."""

from __future__ import annotations

from pathlib import Path

from .config import ChannelConfig
from .formatter import format_message
from .messages import FunhouMessage, LogMessage


def dispatch_message(message: FunhouMessage, channel: ChannelConfig) -> None:
    """Append the formatted message to the configured log file."""

    if isinstance(message, LogMessage) and message.level not in channel.levels:
        return

    _append_line(channel.output, format_message(message))


def _append_line(path: Path, line: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(f"{line}\n")
