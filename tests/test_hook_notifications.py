from pathlib import Path
from unittest.mock import patch

from funhou_hook.config import ChannelConfig, FunhouConfig
from funhou_hook.hook import _build_messages
from funhou_hook.messages import LogMessage


def _config() -> FunhouConfig:
    return FunhouConfig(
        rules=(),
        terminal=ChannelConfig(output=Path("/tmp/test-funhou.log"), levels=("info", "warning", "danger", "error")),
        default_level="warning",
    )


def test_notification_permission_prompt_is_ignored() -> None:
    payload = {
        "hook_event_name": "Notification",
        "notification_type": "permission_prompt",
        "title": "Notification",
        "message": "Claude needs your permission to use Update",
        "session_id": "demo-session",
    }

    messages = _build_messages(payload, _config())

    assert messages == []


def test_notification_idle_prompt_still_emits_log_message() -> None:
    payload = {
        "hook_event_name": "Notification",
        "notification_type": "idle_prompt",
        "title": "Waiting for input",
        "message": "Claude is waiting for your input",
        "session_id": "demo-session",
    }

    messages = _build_messages(payload, _config())

    assert len(messages) == 1
    message = messages[0]
    assert isinstance(message, LogMessage)
    assert message.tool == "Notification"
    assert message.target == "idle_prompt"
    assert message.message == "Waiting for input: Claude is waiting for your input"


def test_other_notifications_still_emit_generic_log_message() -> None:
    payload = {
        "hook_event_name": "Notification",
        "notification_type": "status_update",
        "title": "Background task",
        "message": "Still working",
        "session_id": "demo-session",
    }

    messages = _build_messages(payload, _config())

    assert len(messages) == 1
    message = messages[0]
    assert isinstance(message, LogMessage)
    assert message.tool == "Notification"
    assert message.target == "status_update"
    assert message.message == "Background task: Still working"


def test_post_tool_use_without_pending_is_treated_as_normal_execution() -> None:
    payload = {
        "hook_event_name": "PostToolUse",
        "tool_name": "Bash",
        "tool_input": {"command": "git diff src/pages/noise.astro | head -100"},
        "tool_use_id": "toolu_123",
        "session_id": "demo-session",
    }

    with patch("funhou_hook.hook._pop_pending_approval", return_value=(None, None)):
        messages = _build_messages(payload, _config())

    assert len(messages) == 1
    message = messages[0]
    assert isinstance(message, LogMessage)
    assert message.level == "info"
    assert message.message == "Completed Bash git diff src/pages/noise.astro | head -100"


def test_post_tool_failure_without_pending_is_treated_as_normal_failure() -> None:
    payload = {
        "hook_event_name": "PostToolUseFailure",
        "tool_name": "Bash",
        "tool_input": {"command": "git diff src/pages/noise.astro | head -100"},
        "tool_use_id": "toolu_123",
        "session_id": "demo-session",
        "error": "Command failed",
    }

    with patch("funhou_hook.hook._pop_pending_approval", return_value=(None, None)):
        messages = _build_messages(payload, _config())

    assert len(messages) == 1
    message = messages[0]
    assert isinstance(message, LogMessage)
    assert message.level == "warning"
    assert message.message == "Failed Bash git diff src/pages/noise.astro | head -100: Command failed"


def test_post_tool_use_with_pending_still_emits_approval_granted_and_completed() -> None:
    payload = {
        "hook_event_name": "PostToolUse",
        "tool_name": "Edit",
        "tool_input": {"file_path": "C:\\workspace\\bear-base\\jikken\\src\\pages\\noise.astro"},
        "tool_use_id": "toolu_123",
        "session_id": "demo-session",
    }

    with patch(
        "funhou_hook.hook._pop_pending_approval",
        return_value=({"tool_name": "Edit"}, "tool_use_id"),
    ):
        messages = _build_messages(payload, _config())

    assert len(messages) == 2
    assert isinstance(messages[0], LogMessage)
    assert messages[0].message == "Approval granted: Edit C:\\workspace\\bear-base\\jikken\\src\\pages\\noise.astro"
    assert isinstance(messages[1], LogMessage)
    assert messages[1].message == "Completed Edit C:\\workspace\\bear-base\\jikken\\src\\pages\\noise.astro"
