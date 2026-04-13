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


def main() -> int:
    """Read a hook payload from stdin, classify it, and append one log line."""

    payload = _read_payload(sys.stdin.read())
    config = load_config(_resolve_config_path())
    message = _build_message(payload, config)
    dispatch_message(message, config.terminal)

    sys.stdout.write(json.dumps(_build_response(message, payload), ensure_ascii=False) + "\n")
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


def _build_message(payload: dict[str, Any], config: Any) -> FunhouMessage:
    event_name = str(payload.get("hook_event_name") or "PreToolUse")
    if event_name == "Notification":
        return _build_notification_message(payload, config)
    return _build_tool_message(payload, config)


def _build_tool_message(payload: dict[str, Any], config: Any) -> LogMessage:
    event = _extract_tool_event(payload)
    level = classify_event(event, config)
    return LogMessage(
        timestamp=utc_now(),
        level=level,
        tool=event.tool_name,
        target=event.target,
        message=_describe_event(event),
    )


def _build_notification_message(payload: dict[str, Any], config: Any) -> FunhouMessage:
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
        return ApprovalMessage(
            timestamp=utc_now(),
            level="danger",
            tool="Notification",
            command=title,
            reason=message,
        )

    return LogMessage(
        timestamp=utc_now(),
        level=level,
        tool="Notification",
        target=notification_type,
        message=f"{title}: {message}",
    )


def _build_response(message: FunhouMessage, payload: dict[str, Any]) -> dict[str, str]:
    event_name = str(payload.get("hook_event_name") or "PreToolUse")
    if isinstance(message, ApprovalMessage):
        return {
            "event": event_name,
            "level": message.level,
            "tool": message.tool,
            "target": message.command,
        }

    return {
        "event": event_name,
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


if __name__ == "__main__":
    raise SystemExit(main())
