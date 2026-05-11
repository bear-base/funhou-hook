"""Summary generation orchestration from the terminal funhou log."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal, Protocol

from .config import SummaryEngineConfig, TerminalChannelConfig
from .logging import LogKind, get_logger
from .messages import SummaryMessage, utc_now


class SummaryProvider(Protocol):
    """Use-case level interface implemented by summary providers."""

    def generate_summary(self, source: SummarySource, *, trigger: str) -> SummaryProviderResult:
        """Return a summary result for the supplied log source."""


class SummaryGenerationError(Exception):
    """Raised for retryable or reportable summary generation failures."""


@dataclass(slots=True, frozen=True)
class SummarySource:
    """Log slice used as summary input."""

    text: str
    offset: int
    log_count: int


@dataclass(slots=True, frozen=True)
class SummaryProviderResult:
    """Provider result separated from dispatch metadata."""

    status: Literal["generated", "skipped", "failed"]
    message: str = ""
    next: str = ""
    reason: str | None = None

    @classmethod
    def generated(cls, *, message: str, next: str = "") -> SummaryProviderResult:
        return cls(status="generated", message=message, next=next)

    @classmethod
    def skipped(cls, *, reason: str | None = None) -> SummaryProviderResult:
        return cls(status="skipped", reason=reason)

    @classmethod
    def failed(cls, *, reason: str | None = None) -> SummaryProviderResult:
        return cls(status="failed", reason=reason)


def build_summary_message(
    *,
    trigger: str,
    terminal: TerminalChannelConfig,
    summary: SummaryEngineConfig,
    provider: SummaryProvider,
    now: datetime | None = None,
) -> SummaryMessage | None:
    """Generate a SummaryMessage from new terminal log content when useful."""

    if not summary.enabled:
        return None

    source = read_summary_source(
        terminal.output,
        summary.state_path,
        max_chars=summary.max_log_chars,
    )
    if source.log_count == 0:
        _save_summary_state(summary.state_path, source.offset)
        return None

    try:
        result = provider.generate_summary(source, trigger=trigger)
    except Exception as exc:
        get_logger(LogKind.Debug).warning(
            "Summary generation skipped",
            extra={
                "trigger": trigger,
                "error_type": type(exc).__name__,
                "reason": str(exc),
            },
        )
        return None

    if result.status == "failed":
        get_logger(LogKind.Debug).warning(
            "Summary generation failed",
            extra={"trigger": trigger, "reason": result.reason},
        )
        return None

    if result.status == "skipped":
        _save_summary_state(summary.state_path, source.offset)
        return None

    message = result.message.strip()
    if not message:
        get_logger(LogKind.Debug).warning(
            "Summary provider returned generated result without message",
            extra={"trigger": trigger},
        )
        return None

    timestamp = now or utc_now()
    _save_summary_state(summary.state_path, source.offset)
    return SummaryMessage(
        timestamp=timestamp,
        message=message,
        next=result.next.strip(),
        log_count=source.log_count,
        duration_sec=0,
        trigger=trigger,
    )


def read_summary_source(log_path: Path, state_path: Path, *, max_chars: int) -> SummarySource:
    """Read new terminal log content after the last stored byte offset."""

    if not log_path.exists():
        return SummarySource(text="", offset=0, log_count=0)

    offset = _load_summary_offset(state_path)
    size = log_path.stat().st_size
    if offset > size:
        offset = 0

    with log_path.open("rb") as handle:
        handle.seek(offset)
        raw = handle.read()
        new_offset = handle.tell()

    text = raw.decode("utf-8-sig", errors="replace")
    lines = [line for line in text.splitlines() if line.strip() and "[SUMMARY]" not in line]
    if not lines:
        return SummarySource(text="", offset=new_offset, log_count=0)

    joined = "\n".join(lines)
    if len(joined) > max_chars:
        joined = joined[-max_chars:]
    return SummarySource(text=joined, offset=new_offset, log_count=len(lines))


def _load_summary_offset(path: Path) -> int:
    if not path.exists():
        return 0
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except OSError, json.JSONDecodeError:
        return 0
    if not isinstance(raw, dict):
        return 0
    try:
        return int(raw.get("offset", 0))
    except TypeError, ValueError:
        return 0


def _save_summary_state(path: Path, offset: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"offset": offset}, ensure_ascii=True, sort_keys=True),
        encoding="utf-8",
    )
