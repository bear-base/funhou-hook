from __future__ import annotations

import shutil
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest

from funhou_hook.config import SlackChannelConfig, TerminalChannelConfig
from funhou_hook.dispatcher import dispatch_message
from funhou_hook.logging import LogKind, get_logger, initialize_logging
from funhou_hook.messages import ApprovalMessage, LogMessage, SummaryMessage
from funhou_hook.slack_sender import SlackDeliveryError


@pytest.fixture
def runtime_dir() -> Iterator[Path]:
    path = Path(__file__).resolve().parent / ".tmp" / uuid.uuid4().hex
    path.mkdir(parents=True, exist_ok=False)
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)
        for kind in LogKind:
            logger = get_logger(kind)
            handlers = list(logger.handlers)
            for handler in handlers:
                logger.removeHandler(handler)
                handler.close()


def _terminal_channel(
    path: Path,
    *,
    levels: tuple[str, ...] = ("info", "warning", "danger", "error"),
    message_types: tuple[str, ...] = ("log", "summary", "approval"),
) -> TerminalChannelConfig:
    return TerminalChannelConfig(
        output=path,
        levels=levels,
        message_types=message_types,
    )


def _slack_channel(
    *,
    enabled: bool = True,
    levels: tuple[str, ...] = ("info", "warning", "danger", "error"),
    message_types: tuple[str, ...] = ("log", "summary", "approval"),
) -> SlackChannelConfig:
    return SlackChannelConfig(
        enabled=enabled,
        webhook="https://hooks.slack.com/services/T000/B000/XXXX" if enabled else None,
        levels=levels,
        message_types=message_types,
    )


def _log_message(level: str = "info") -> LogMessage:
    return LogMessage(
        timestamp=datetime(2026, 4, 9, 10, 3, tzinfo=UTC),
        level=level,
        tool="Read",
        target="src/config.ts",
        message="Read src/config.ts",
    )


def _summary_message() -> SummaryMessage:
    return SummaryMessage(
        timestamp=datetime(2026, 4, 9, 10, 15, tzinfo=UTC),
        message="Config updated and tests passed.",
        next="Run migration",
        log_count=12,
        duration_sec=720,
    )


def _approval_message() -> ApprovalMessage:
    return ApprovalMessage(
        timestamp=datetime(2026, 4, 9, 10, 16, tzinfo=UTC),
        level="danger",
        tool="Bash",
        command="npx prisma migrate deploy",
        reason="Production migration",
    )


def test_dispatch_message_writes_log_when_type_and_level_match(runtime_dir: Path) -> None:
    terminal_path = runtime_dir / "funhou.log"

    dispatch_message(
        _log_message(level="warning"),
        _terminal_channel(terminal_path, levels=("warning",), message_types=("log",)),
    )

    contents = terminal_path.read_text(encoding="utf-8-sig")
    assert "Read src/config.ts" in contents


def test_dispatch_message_skips_log_when_message_type_is_filtered(runtime_dir: Path) -> None:
    terminal_path = runtime_dir / "funhou.log"

    dispatch_message(
        _log_message(),
        _terminal_channel(terminal_path, message_types=("summary", "approval")),
    )

    assert not terminal_path.exists()


def test_dispatch_message_skips_log_when_level_is_filtered(runtime_dir: Path) -> None:
    terminal_path = runtime_dir / "funhou.log"

    dispatch_message(
        _log_message(level="info"),
        _terminal_channel(terminal_path, levels=("warning", "danger"), message_types=("log",)),
    )

    assert not terminal_path.exists()


def test_dispatch_message_delivers_summary_by_message_type_only(runtime_dir: Path) -> None:
    terminal_path = runtime_dir / "funhou.log"

    dispatch_message(
        _summary_message(),
        _terminal_channel(terminal_path, levels=(), message_types=("summary",)),
    )

    contents = terminal_path.read_text(encoding="utf-8-sig")
    assert "[SUMMARY]" in contents
    assert "Config updated and tests passed." in contents
    assert "Run migration" in contents


def test_dispatch_message_filters_approval_by_type_and_level(runtime_dir: Path) -> None:
    terminal_path = runtime_dir / "funhou.log"

    dispatch_message(
        _approval_message(),
        _terminal_channel(terminal_path, levels=("danger",), message_types=("approval",)),
    )

    contents = terminal_path.read_text(encoding="utf-8-sig")
    assert "[APPROVAL]" in contents
    assert "npx prisma migrate deploy" in contents


def test_dispatch_message_skips_approval_when_type_is_not_enabled(runtime_dir: Path) -> None:
    terminal_path = runtime_dir / "funhou.log"

    dispatch_message(
        _approval_message(),
        _terminal_channel(terminal_path, levels=("danger",), message_types=("log", "summary")),
    )

    assert not terminal_path.exists()


def test_dispatch_message_skips_disabled_slack(
    runtime_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    terminal_path = runtime_dir / "funhou.log"
    delivered: list[str] = []

    monkeypatch.setattr(
        "funhou_hook.dispatcher.send_slack_message",
        lambda message, config: delivered.append(message.type),
    )

    dispatch_message(
        _log_message(),
        _terminal_channel(terminal_path),
        _slack_channel(enabled=False),
    )

    assert delivered == []
    assert "Read src/config.ts" in terminal_path.read_text(encoding="utf-8-sig")


def test_dispatch_message_logs_slack_failure_and_keeps_terminal_output(
    runtime_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    terminal_path = runtime_dir / "funhou.log"
    operational_log_path = runtime_dir / "operational.log"
    initialize_logging(operational_log_path)

    def fail_send(message: object, config: object) -> None:
        raise SlackDeliveryError("Slack webhook returned HTTP 500.")

    monkeypatch.setattr("funhou_hook.dispatcher.send_slack_message", fail_send)

    dispatch_message(
        _log_message(),
        _terminal_channel(terminal_path, message_types=("log",)),
        _slack_channel(message_types=("log",)),
    )

    assert "Read src/config.ts" in terminal_path.read_text(encoding="utf-8-sig")
    operational_log = operational_log_path.read_text(encoding="utf-8")
    assert "[ERROR] Slack delivery failed" in operational_log
    assert "channel='slack'" in operational_log
    assert "event_type='log'" in operational_log
    assert "HTTP 500" in operational_log


def test_dispatch_message_raises_when_terminal_delivery_fails(
    runtime_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    terminal_path = runtime_dir / "funhou.log"
    slack_calls: list[str] = []

    monkeypatch.setattr(
        "funhou_hook.dispatcher._append_line",
        lambda path, line: (_ for _ in ()).throw(OSError("disk full")),
    )
    monkeypatch.setattr(
        "funhou_hook.dispatcher.send_slack_message",
        lambda message, config: slack_calls.append(message.type),
    )

    with pytest.raises(OSError, match="disk full"):
        dispatch_message(
            _log_message(),
            _terminal_channel(terminal_path, message_types=("log",)),
            _slack_channel(message_types=("log",)),
        )

    assert slack_calls == []
