from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from funhou_hook.config import ChannelConfig, FunhouConfig, SummaryEngineConfig
from funhou_hook.hook import _build_messages, _build_response
from funhou_hook.messages import ApprovalMessage, SummaryMessage


def _config() -> FunhouConfig:
    return FunhouConfig(
        rules=(),
        terminal=ChannelConfig(
            output=Path("/tmp/test-funhou.log"),
            levels=("info", "warning", "danger", "error"),
        ),
        summary=SummaryEngineConfig(enabled=True),
        default_level="warning",
    )


def _summary(trigger: str, _config: object) -> SummaryMessage:
    return SummaryMessage(
        timestamp=datetime(2026, 4, 9, 10, 15, tzinfo=UTC),
        message=f"Summary for {trigger}",
        next="Continue",
        log_count=2,
        duration_sec=0,
        trigger=trigger,
    )


def test_stop_event_generates_summary_message(monkeypatch) -> None:
    monkeypatch.setattr("funhou_hook.hook._build_summary_for_trigger", _summary)

    messages = _build_messages({"hook_event_name": "Stop"}, _config())

    assert messages == [_summary("Stop", _config())]


def test_permission_request_generates_summary_before_approval(monkeypatch) -> None:
    saved: list[tuple[str, str, str]] = []
    monkeypatch.setattr("funhou_hook.hook._build_summary_for_trigger", _summary)
    monkeypatch.setattr(
        "funhou_hook.hook._put_pending_approval",
        lambda key, mode, session_id, event: saved.append((key, mode, session_id)),
    )
    payload = {
        "hook_event_name": "PermissionRequest",
        "tool_name": "Bash",
        "tool_input": {
            "command": "npx prisma migrate deploy",
            "description": "production migration",
        },
        "session_id": "demo-session",
        "tool_use_id": "toolu_123",
    }

    messages = _build_messages(payload, _config())

    assert isinstance(messages[0], SummaryMessage)
    assert messages[0].trigger == "PermissionRequest"
    assert isinstance(messages[1], ApprovalMessage)
    assert messages[1].reason == "production migration"
    assert saved == [("toolu_123", "tool_use_id", "demo-session")]


def test_summary_response_uses_trigger_without_level() -> None:
    response = _build_response(_summary("Stop", _config()))

    assert response == {"type": "summary", "target": "Stop"}
