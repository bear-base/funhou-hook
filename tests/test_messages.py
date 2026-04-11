from datetime import UTC, datetime

from funhou_hook import ApprovalMessage, LogMessage, SummaryMessage
from funhou_hook.messages import utc_now


def test_log_message_matches_design_contract() -> None:
    message = LogMessage(
        timestamp=datetime(2026, 4, 9, 10, 3, tzinfo=UTC),
        level="info",
        tool="Read",
        target="src/config.ts",
        message="Read src/config.ts",
    )

    assert message.type == "log"
    assert message.level == "info"
    assert message.tool == "Read"


def test_summary_message_captures_checkpoint_fields() -> None:
    message = SummaryMessage(
        timestamp=datetime(2026, 4, 9, 10, 15, tzinfo=UTC),
        message="config.ts updated and tests passed.",
        next="Run migration after approval.",
        log_count=12,
        duration_sec=720,
    )

    assert message.type == "summary"
    assert message.log_count == 12
    assert message.duration_sec == 720


def test_approval_message_defaults_to_waiting_for_a_response() -> None:
    message = ApprovalMessage(
        timestamp=datetime(2026, 4, 9, 10, 16, tzinfo=UTC),
        level="danger",
        tool="Bash",
        command="uv run deploy",
        reason="production deployment",
    )

    assert message.type == "approval"
    assert message.await_response is True


def test_utc_now_returns_timezone_aware_utc() -> None:
    now = utc_now()

    assert now.tzinfo is UTC
