"""Phase 1 hook entrypoint for Claude Code events."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from .classifier import ToolEvent, classify_event
from .config import load_config
from .dispatcher import dispatch_message
from .messages import ApprovalMessage, FunhouMessage, LogMessage, utc_now

APPROVAL_STATE_PATH = Path("/tmp/funhou-approval-state.json")
DEBUG_LOG_PATH = Path("/tmp/funhou-debug.log")


def main() -> int:
    """Read a hook payload from stdin, map it to messages, and append log lines."""

    payload = _read_payload(sys.stdin.read())
    _debug_event_payload(payload)
    config = load_config(_resolve_config_path())
    messages = _build_messages(payload, config)
    for message in messages:
        dispatch_message(message, config.terminal)

    response = {"event": str(payload.get("hook_event_name") or "unknown")}
    if messages:
        response.update(_build_response(messages[-1]))
    sys.stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
    return 0


def _resolve_config_path() -> Path | None:
    raw_path = sys.argv[1] if len(sys.argv) > 1 else None
    if raw_path:
        return Path(raw_path)
    return None


def _read_payload(raw: str) -> dict[str, Any]:
    if not raw.strip():
        raise ValueError("Hook stdin is empty.")
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise ValueError("Hook stdin must be a JSON object.")
    return payload


def _build_messages(payload: dict[str, Any], config: Any) -> list[FunhouMessage]:
    event_name = str(payload.get("hook_event_name") or "PreToolUse")
    if event_name == "Notification":
        return _build_notification_messages(payload, config)
    if event_name == "PermissionRequest":
        return _handle_permission_request(payload)
    if event_name == "PermissionDenied":
        return _build_permission_denied_messages(payload)
    if event_name == "PostToolUse":
        return _build_post_tool_use_messages(payload)
    if event_name == "PostToolUseFailure":
        return _build_post_tool_failure_messages(payload)
    return [_build_pre_tool_use_message(payload, config)]


def _build_pre_tool_use_message(payload: dict[str, Any], config: Any) -> LogMessage:
    event = _extract_tool_event(payload)
    level = classify_event(event, config)
    return LogMessage(
        timestamp=utc_now(),
        level=level,
        tool=event.tool_name,
        target=event.target,
        message=_describe_event(event),
    )


def _build_notification_messages(payload: dict[str, Any], config: Any) -> list[FunhouMessage]:
    notification_type = str(payload.get("notification_type") or "notification")
    title = str(payload.get("title") or "Notification")
    message = str(payload.get("message") or notification_type)

    event = ToolEvent(
        tool_name="Notification",
        target=notification_type,
        payload=payload,
    )
    level = classify_event(event, config)

    if notification_type == "permission_prompt":
        return [
            ApprovalMessage(
                timestamp=utc_now(),
                level="danger",
                tool="Notification",
                command=title,
                reason=message,
            )
        ]

    return [
        LogMessage(
            timestamp=utc_now(),
            level=level,
            tool="Notification",
            target=notification_type,
            message=f"{title}: {message}",
        )
    ]


def _handle_permission_request(payload: dict[str, Any]) -> list[FunhouMessage]:
    event = _extract_tool_event(payload)
    _put_pending_approval(str(payload.get("session_id") or "unknown"), event)
    return []


def _build_permission_denied_messages(payload: dict[str, Any]) -> list[FunhouMessage]:
    event = _extract_tool_event(payload)
    session_id = str(payload.get("session_id") or "unknown")
    pending = _pop_pending_approval(session_id, event)
    reason = str(payload.get("reason") or "Permission denied")

    prefix = "Approval denied" if pending else "Denied"
    return [
        LogMessage(
            timestamp=utc_now(),
            level="danger",
            tool=event.tool_name,
            target=event.target,
            message=f"{prefix}: {event.tool_name} {event.target} ({reason})",
        )
    ]


def _build_post_tool_use_messages(payload: dict[str, Any]) -> list[FunhouMessage]:
    event = _extract_tool_event(payload)
    session_id = str(payload.get("session_id") or "unknown")
    pending = _pop_pending_approval(session_id, event)

    messages: list[FunhouMessage] = []
    if pending:
        messages.append(
            LogMessage(
                timestamp=utc_now(),
                level="info",
                tool=event.tool_name,
                target=event.target,
                message=f"Approval granted: {event.tool_name} {event.target}",
            )
        )

    messages.append(
        LogMessage(
            timestamp=utc_now(),
            level="info",
            tool=event.tool_name,
            target=event.target,
            message=f"Completed {event.tool_name} {event.target}",
        )
    )
    return messages


def _build_post_tool_failure_messages(payload: dict[str, Any]) -> list[FunhouMessage]:
    event = _extract_tool_event(payload)
    session_id = str(payload.get("session_id") or "unknown")
    pending = _pop_pending_approval(session_id, event)
    error = str(payload.get("error") or "Tool execution failed")

    messages: list[FunhouMessage] = []
    if pending:
        messages.append(
            LogMessage(
                timestamp=utc_now(),
                level="info",
                tool=event.tool_name,
                target=event.target,
                message=f"Approval granted: {event.tool_name} {event.target}",
            )
        )

    messages.append(
        LogMessage(
            timestamp=utc_now(),
            level="warning",
            tool=event.tool_name,
            target=event.target,
            message=f"Failed {event.tool_name} {event.target}: {error}",
        )
    )
    return messages


def _build_response(message: FunhouMessage) -> dict[str, str]:
    if isinstance(message, ApprovalMessage):
        return {
            "level": message.level,
            "tool": message.tool,
            "target": message.command,
        }
    return {
        "level": message.level,
        "tool": message.tool,
        "target": message.target,
    }


def _extract_tool_event(payload: dict[str, Any]) -> ToolEvent:
    tool_name = str(payload.get("tool_name") or payload.get("tool") or "unknown")
    tool_input = payload.get("tool_input")
    if not isinstance(tool_input, dict):
        tool_input = {}

    target = _extract_target(tool_name, tool_input)
    return ToolEvent(tool_name=tool_name, target=target, payload=payload)


def _extract_target(tool_name: str, tool_input: dict[str, Any]) -> str:
    preferred_keys = (
        "file_path",
        "path",
        "target",
        "command",
        "cmd",
        "pattern",
        "query",
    )
    for key in preferred_keys:
        value = tool_input.get(key)
        if value:
            return str(value)

    if tool_name == "Bash":
        command = tool_input.get("command")
        if command:
            return str(command)

    if tool_input:
        return json.dumps(tool_input, ensure_ascii=False, sort_keys=True)
    return "<no-target>"


def _describe_event(event: ToolEvent) -> str:
    return f"{event.tool_name} {event.target}"


def _approval_key(session_id: str, event: ToolEvent) -> str:
    return f"{session_id}::{event.signature}"


def _load_pending_approvals() -> dict[str, dict[str, str]]:
    if not APPROVAL_STATE_PATH.exists():
        return {}
    raw = json.loads(APPROVAL_STATE_PATH.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        return {}
    return {
        str(key): {str(k): str(v) for k, v in value.items()}
        for key, value in raw.items()
        if isinstance(value, dict)
    }


def _save_pending_approvals(state: dict[str, dict[str, str]]) -> None:
    APPROVAL_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    APPROVAL_STATE_PATH.write_text(
        json.dumps(state, ensure_ascii=False, sort_keys=True, indent=2),
        encoding="utf-8",
    )


def _debug_event_payload(payload: dict[str, Any]) -> None:
    DEBUG_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "hook_event_name": payload.get("hook_event_name"),
        "notification_type": payload.get("notification_type"),
        "tool_name": payload.get("tool_name"),
        "title": payload.get("title"),
        "message": payload.get("message"),
        "payload": payload,
    }
    with DEBUG_LOG_PATH.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")


def _put_pending_approval(session_id: str, event: ToolEvent) -> None:
    state = _load_pending_approvals()
    state[_approval_key(session_id, event)] = {
        "tool_name": event.tool_name,
        "target": event.target,
    }
    _save_pending_approvals(state)


def _pop_pending_approval(session_id: str, event: ToolEvent) -> dict[str, str] | None:
    state = _load_pending_approvals()
    pending = state.pop(_approval_key(session_id, event), None)
    if pending is not None or state:
        _save_pending_approvals(state)
    elif APPROVAL_STATE_PATH.exists():
        APPROVAL_STATE_PATH.unlink()
    return pending


if __name__ == "__main__":
    raise SystemExit(main())
