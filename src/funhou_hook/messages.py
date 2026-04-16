"""Core message types shared by hooks, summarizers, and adapters."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

Level = Literal["info", "warning", "danger", "error"]
MessageType = Literal["log", "summary", "approval"]


def utc_now() -> datetime:
    """Return a timezone-aware UTC timestamp."""

    return datetime.now(UTC)


@dataclass(slots=True, frozen=True)
class LogMessage:
    """A single tool activity emitted by the agent."""

    timestamp: datetime
    level: Level
    tool: str
    target: str
    message: str
    type: MessageType = "log"


@dataclass(slots=True, frozen=True)
class SummaryMessage:
    """A checkpoint summary emitted after a meaningful chunk of work."""

    timestamp: datetime
    message: str
    next: str
    log_count: int
    duration_sec: int
    type: MessageType = "summary"


@dataclass(slots=True, frozen=True)
class ApprovalMessage:
    """A message that pauses execution until a human responds."""

    timestamp: datetime
    level: Literal["danger"]
    tool: str
    command: str
    reason: str
    await_response: bool = True
    type: MessageType = "approval"


FunhouMessage = LogMessage | SummaryMessage | ApprovalMessage