"""Phase 1 hook entrypoint for Claude Code events."""

from __future__ import annotations

import json
import sys
import traceback
import uuid
from codecs import BOM_UTF8
from pathlib import Path
from typing import Any

from .classifier import ToolEvent, classify_event
from .config import DEFAULT_CONFIG_PATH, DEFAULT_LOG_PATH, load_config
from .dispatcher import dispatch_message
from .formatter import format_message
from .logging import LogKind, get_logger, initialize_logging
from .messages import ApprovalMessage, FunhouMessage, LogMessage, utc_now

APPROVAL_STATE_PATH = Path("/tmp/funhou-approval-state.json")
BROKEN_STATE_PATH = Path("/tmp/funhou-approval-state.json.broken")
DEBUG_LOG_PATH = Path("/tmp/funhou-debug.log")
# TEMP DEBUG: dedicated correlation log for approval matching investigation.
CORRELATION_DEBUG_LOG_PATH = Path("/tmp/funhou-correlation-debug.log")
INPUT_DEBUG_LOG_PATH = Path("/tmp/funhou-input-debug.log")
RUNTIME_ERROR_NOTIFICATION = "エラーが発生しました。詳細はログを確認してください。"


def main() -> int:
    """Read a hook payload from stdin, map it to messages, and append log lines."""

    payload: dict[str, Any] | None = None
    config: Any | None = None
    initialize_logging()
    try:
        config_path = _resolve_config_path()
        raw_stdin = _read_stdin_bytes()
        payload = _read_payload(_decode_stdin_bytes(raw_stdin))
        _log_hook_received(payload)

        config = load_config(config_path)
        _log_config_loaded(config_path)

        messages = _build_messages(payload, config)
        _debug_stage(
            "main.messages_built",
            payload,
            message_count=len(messages),
            message_types=[message.type for message in messages],
        )

        for index, message in enumerate(messages):
            _debug_stage(
                "main.dispatching_message",
                payload,
                index=index,
                message_type=message.type,
                level=getattr(message, "level", None),
            )
            dispatch_message(message, config.terminal)

        response = {"event": str(payload.get("hook_event_name") or "unknown")}
        if messages:
            response.update(_build_response(messages[-1]))
        _debug_stage("main.response_ready", payload, response=response)
        sys.stdout.write(json.dumps(response, ensure_ascii=True) + "\n")
        return 0
    except Exception as exc:
        _log_runtime_error(exc, payload)
        _emit_runtime_error(exc, payload, config)
        raise


def _resolve_config_path() -> Path | None:
    raw_path = sys.argv[1] if len(sys.argv) > 1 else None
    if raw_path:
        return Path(raw_path)
    return None


def _read_stdin_bytes() -> bytes:
    buffer = getattr(sys.stdin, "buffer", None)
    if buffer is not None:
        return buffer.read()
    return sys.stdin.read().encode("utf-8")


def _decode_stdin_bytes(raw: bytes) -> str:
    return raw.decode("utf-8")


def _read_payload(raw: str) -> dict[str, Any]:
    if not raw.strip():
        raise ValueError("Hook stdin is empty.")
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise ValueError("Hook stdin must be a JSON object.")
    return payload


def _log_hook_received(payload: dict[str, Any]) -> None:
    get_logger(LogKind.Operational).info(
        "Hook received",
        extra={"event_type": _event_type(payload), "source": "stdin"},
    )


def _log_config_loaded(path: Path | None) -> None:
    config_path = path or DEFAULT_CONFIG_PATH
    get_logger(LogKind.Operational).info(
        "Config loaded",
        extra={"config_path": str(config_path)},
    )


def _log_runtime_error(exc: Exception, payload: dict[str, Any] | None) -> None:
    get_logger(LogKind.Operational).error(
        "Hook runtime error",
        extra={
            "event_type": _event_type(payload),
            "error_type": type(exc).__name__,
            "error_message": str(exc),
            "stack_trace": traceback.format_exc(),
        },
    )


def _event_type(payload: dict[str, Any] | None) -> str:
    if payload is None:
        return "unknown"
    return str(payload.get("hook_event_name") or "unknown")


def _build_messages(payload: dict[str, Any], config: Any) -> list[FunhouMessage]:
    event_name = str(payload.get("hook_event_name") or "PreToolUse")
    _debug_stage("build_messages.start", payload, event_name=event_name)
    if event_name == "Notification":
        messages = _build_notification_messages(payload, config)
    elif event_name == "PermissionRequest":
        messages = _handle_permission_request(payload)
    elif event_name == "PermissionDenied":
        messages = _build_permission_denied_messages(payload)
    elif event_name == "PostToolUse":
        messages = _build_post_tool_use_messages(payload)
    elif event_name == "PostToolUseFailure":
        messages = _build_post_tool_failure_messages(payload)
    else:
        messages = [_build_pre_tool_use_message(payload, config)]
    _debug_stage(
        "build_messages.done",
        payload,
        event_name=event_name,
        message_count=len(messages),
        message_types=[message.type for message in messages],
    )
    return messages


def _build_pre_tool_use_message(payload: dict[str, Any], config: Any) -> LogMessage:
    event = _extract_tool_event(payload)
    level = classify_event(event, config)
    _debug_stage("pre_tool_use.classified", payload, level=level, target=event.target)
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
    _debug_stage(
        "notification.classified",
        payload,
        notification_type=notification_type,
        level=level,
    )

    if notification_type == "permission_prompt":
        _debug_stage(
            "notification.ignored",
            payload,
            notification_type=notification_type,
            reason="permission_prompt is redundant with PermissionRequest",
        )
        return []

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
    session_id = str(payload.get("session_id") or "unknown")
    messages: list[FunhouMessage] = []
    _debug_stage("permission_request.start", payload, session_id=session_id)

    tool_use_id, fallback_key = _extract_correlation_keys(payload, event)
    save_key = tool_use_id or fallback_key
    save_mode = "tool_use_id" if tool_use_id else "fallback_key"
    _debug_correlation(
        "PermissionRequest",
        payload,
        event,
        tool_use_id=tool_use_id,
        fallback_key=fallback_key,
        decision=f"save_by_{save_mode}",
        matched_by=save_mode,
        result="pending_saved",
    )
    _put_pending_approval(save_key, save_mode, session_id, event)

    description = _extract_description(payload)
    message = f"Permission requested: {event.tool_name} {event.target}"
    if description:
        message = f"{message} ({description})"
    _debug_stage("permission_request.message_ready", payload, message=message)
    messages.append(
        ApprovalMessage(
            timestamp=utc_now(),
            level="danger",
            tool=event.tool_name,
            command=event.target,
            reason=message,
        )
    )
    return messages


def _build_permission_denied_messages(payload: dict[str, Any]) -> list[FunhouMessage]:
    event = _extract_tool_event(payload)
    session_id = str(payload.get("session_id") or "unknown")
    messages: list[FunhouMessage] = []
    _debug_stage("permission_denied.start", payload, session_id=session_id)

    tool_use_id, fallback_key = _extract_correlation_keys(payload, event)
    pending, matched_by = _pop_pending_approval(tool_use_id, fallback_key)
    _debug_correlation(
        "PermissionDenied",
        payload,
        event,
        tool_use_id=tool_use_id,
        fallback_key=fallback_key,
        decision="match_result",
        matched_by=matched_by,
        result="matched" if pending else "match_failed",
    )

    if pending is None:
        messages.append(
            _error_message(
                event.target,
                (
                    "Approval result could not be correlated for "
                    f"{event.tool_name}; tool_use_id={tool_use_id or '<missing>'}, "
                    f"fallback_key={fallback_key}"
                ),
            )
        )

    reason = str(payload.get("reason") or "Permission denied")
    prefix = "Approval denied" if pending else "Denied"
    _debug_stage(
        "permission_denied.done",
        payload,
        had_pending=pending is not None,
        reason=reason,
        matched_by=matched_by,
    )
    messages.append(
        LogMessage(
            timestamp=utc_now(),
            level="danger",
            tool=event.tool_name,
            target=event.target,
            message=f"{prefix}: {event.tool_name} {event.target} ({reason})",
        )
    )
    return messages


def _build_post_tool_use_messages(payload: dict[str, Any]) -> list[FunhouMessage]:
    event = _extract_tool_event(payload)
    session_id = str(payload.get("session_id") or "unknown")
    messages: list[FunhouMessage] = []
    _debug_stage("post_tool_use.start", payload, session_id=session_id)

    tool_use_id, fallback_key = _extract_correlation_keys(payload, event)
    pending, matched_by = _pop_pending_approval(tool_use_id, fallback_key)
    _debug_correlation(
        "PostToolUse",
        payload,
        event,
        tool_use_id=tool_use_id,
        fallback_key=fallback_key,
        decision="match_result",
        matched_by=matched_by,
        result="matched" if pending else "match_failed",
    )

    if pending is not None:
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
    _debug_stage(
        "post_tool_use.done",
        payload,
        had_pending=pending is not None,
        matched_by=matched_by,
        message_count=len(messages),
    )
    return messages


def _build_post_tool_failure_messages(payload: dict[str, Any]) -> list[FunhouMessage]:
    event = _extract_tool_event(payload)
    session_id = str(payload.get("session_id") or "unknown")
    messages: list[FunhouMessage] = []
    _debug_stage("post_tool_failure.start", payload, session_id=session_id)

    tool_use_id, fallback_key = _extract_correlation_keys(payload, event)
    pending, matched_by = _pop_pending_approval(tool_use_id, fallback_key)
    _debug_correlation(
        "PostToolUseFailure",
        payload,
        event,
        tool_use_id=tool_use_id,
        fallback_key=fallback_key,
        decision="match_result",
        matched_by=matched_by,
        result="matched" if pending else "match_failed",
    )
    error = _extract_error(payload)

    if pending is not None:
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
    _debug_stage(
        "post_tool_failure.done",
        payload,
        had_pending=pending is not None,
        matched_by=matched_by,
        error=error,
        message_count=len(messages),
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
        return json.dumps(tool_input, ensure_ascii=True, sort_keys=True)
    return "<no-target>"


def _extract_description(payload: dict[str, Any]) -> str | None:
    tool_input = payload.get("tool_input")
    if not isinstance(tool_input, dict):
        return None
    description = tool_input.get("description")
    if description is None:
        return None
    return str(description)


def _extract_error(payload: dict[str, Any]) -> str:
    if payload.get("error"):
        return str(payload["error"])
    tool_response = payload.get("tool_response")
    if isinstance(tool_response, dict) and tool_response.get("stderr"):
        return str(tool_response["stderr"])
    return "Tool execution failed"


def _extract_tool_use_id(payload: dict[str, Any]) -> str | None:
    tool_use_id = payload.get("tool_use_id")
    if tool_use_id is None:
        return None
    raw = str(tool_use_id).strip()
    return raw or None


def _extract_correlation_keys(payload: dict[str, Any], event: ToolEvent) -> tuple[str | None, str]:
    session_id = str(payload.get("session_id") or "unknown")
    return _extract_tool_use_id(payload), _fallback_approval_key(session_id, event)


def _describe_event(event: ToolEvent) -> str:
    return f"{event.tool_name} {event.target}"


def _fallback_approval_key(session_id: str, event: ToolEvent) -> str:
    return f"{session_id}::{event.tool_name}::{event.target}"


def _load_pending_approvals() -> dict[str, dict[str, str]]:
    _debug_stage("state.load.start", None, path=str(APPROVAL_STATE_PATH))
    if not APPROVAL_STATE_PATH.exists():
        _debug_stage("state.load.missing", None, path=str(APPROVAL_STATE_PATH))
        return {}

    raw_text = APPROVAL_STATE_PATH.read_text(encoding="utf-8")
    _debug_stage("state.load.read", None, bytes=len(raw_text.encode()), chars=len(raw_text))
    try:
        raw = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        _debug_stage("state.load.invalid_json", None, error=str(exc))
        _recover_broken_state(raw_text, exc)
        return {}

    if not isinstance(raw, dict):
        _debug_stage("state.load.not_dict", None, raw_type=type(raw).__name__)
        _recover_broken_state(
            raw_text,
            ValueError("Approval state file must contain a JSON object."),
        )
        return {}

    state = {
        str(key): {str(k): str(v) for k, v in value.items()}
        for key, value in raw.items()
        if isinstance(value, dict)
    }
    _debug_stage("state.load.done", None, entry_count=len(state), keys=list(state.keys()))
    return state


def _save_pending_approvals(state: dict[str, dict[str, str]]) -> None:
    APPROVAL_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    _debug_stage("state.save.start", None, path=str(APPROVAL_STATE_PATH), entry_count=len(state))
    temp_path = APPROVAL_STATE_PATH.with_name(f"{APPROVAL_STATE_PATH.name}.{uuid.uuid4().hex}.tmp")
    try:
        temp_path.write_text(
            json.dumps(state, ensure_ascii=True, sort_keys=True, indent=2),
            encoding="utf-8",
        )
        temp_path.replace(APPROVAL_STATE_PATH)
    finally:
        if temp_path.exists():
            temp_path.unlink()
    _debug_stage("state.save.done", None, path=str(APPROVAL_STATE_PATH), entry_count=len(state))


def _recover_broken_state(raw_text: str, exc: Exception) -> None:
    BROKEN_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    BROKEN_STATE_PATH.write_text(raw_text, encoding="utf-8")
    _save_pending_approvals({})
    _append_operational_log(
        _error_message(
            str(APPROVAL_STATE_PATH),
            (
                "Approval state was invalid; backed up to "
                f"{BROKEN_STATE_PATH} and continued with an empty state ({exc})."
            ),
        )
    )
    _debug_stage(
        "state.recovered",
        None,
        path=str(APPROVAL_STATE_PATH),
        broken_path=str(BROKEN_STATE_PATH),
        error=str(exc),
    )


def _debug_raw_stdin(raw: bytes) -> None:
    return


def _debug_event_payload(payload: dict[str, Any]) -> None:
    record = {
        "event": "payload",
        "hook_event_name": payload.get("hook_event_name"),
        "notification_type": payload.get("notification_type"),
        "tool_name": payload.get("tool_name"),
        "title": payload.get("title"),
        "message": payload.get("message"),
        "payload": payload,
    }
    _append_debug_record(record)


def _debug_stage(stage: str, payload: dict[str, Any] | None, **extra: Any) -> None:
    record: dict[str, Any] = {"event": "stage", "stage": stage}
    if payload is not None:
        record.update(
            {
                "hook_event_name": payload.get("hook_event_name"),
                "notification_type": payload.get("notification_type"),
                "session_id": payload.get("session_id"),
                "tool_use_id": payload.get("tool_use_id"),
                "tool_name": payload.get("tool_name"),
            }
        )
        tool_input = payload.get("tool_input")
        if isinstance(tool_input, dict):
            record["target"] = _extract_target(
                str(payload.get("tool_name") or "unknown"),
                tool_input,
            )
    record.update(extra)
    _append_debug_record(record)


def _debug_exception(payload: dict[str, Any] | None, exc: Exception) -> None:
    record: dict[str, Any] = {
        "event": "exception",
        "error_type": type(exc).__name__,
        "error_message": str(exc),
        "traceback": traceback.format_exc(),
    }
    if payload is not None:
        record.update(
            {
                "hook_event_name": payload.get("hook_event_name"),
                "notification_type": payload.get("notification_type"),
                "session_id": payload.get("session_id"),
                "tool_use_id": payload.get("tool_use_id"),
                "tool_name": payload.get("tool_name"),
            }
        )
    _append_debug_record(record)


def _append_debug_record(record: dict[str, Any]) -> None:
    return


def _debug_correlation(
    hook_event_name: str,
    payload: dict[str, Any],
    event: ToolEvent,
    *,
    tool_use_id: str | None,
    fallback_key: str,
    decision: str,
    matched_by: str,
    result: str,
) -> None:
    """TEMP DEBUG: make approval correlation decisions obvious in one place."""

    return


def _put_pending_approval(
    correlation_key: str,
    key_type: str,
    session_id: str,
    event: ToolEvent,
) -> None:
    _debug_stage(
        "state.put.start",
        None,
        correlation_key=correlation_key,
        key_type=key_type,
        session_id=session_id,
        tool_name=event.tool_name,
        target=event.target,
    )
    state = _load_pending_approvals()
    state[correlation_key] = {
        "session_id": session_id,
        "tool_name": event.tool_name,
        "target": event.target,
        "key_type": key_type,
    }
    _save_pending_approvals(state)
    _debug_stage(
        "state.put.done",
        None,
        correlation_key=correlation_key,
        key_type=key_type,
        entry_count=len(state),
    )


def _pop_pending_approval(
    tool_use_id: str | None,
    fallback_key: str,
) -> tuple[dict[str, str] | None, str]:
    state = _load_pending_approvals()

    if tool_use_id is not None:
        _debug_stage("state.pop.try_tool_use_id", None, correlation_key=tool_use_id)
        pending = state.pop(tool_use_id, None)
        if pending is not None:
            _debug_stage(
                "state.pop.matched",
                None,
                correlation_key=tool_use_id,
                matched_by="tool_use_id",
            )
            _save_pending_after_pop(state)
            return pending, "tool_use_id"

    _debug_stage("state.pop.try_fallback_key", None, correlation_key=fallback_key)
    pending = state.pop(fallback_key, None)
    if pending is not None:
        _debug_stage(
            "state.pop.matched",
            None,
            correlation_key=fallback_key,
            matched_by="fallback_key",
        )
        _save_pending_after_pop(state)
        return pending, "fallback_key"

    _debug_stage(
        "state.pop.after_pop",
        None,
        tool_use_id=tool_use_id,
        fallback_key=fallback_key,
        found=False,
        entry_count=len(state),
    )
    return None, "none"


def _save_pending_after_pop(state: dict[str, dict[str, str]]) -> None:
    if state:
        _save_pending_approvals(state)
    elif APPROVAL_STATE_PATH.exists():
        _save_pending_approvals({})
        _debug_stage("state.pop.cleared", None, path=str(APPROVAL_STATE_PATH))


def _error_message(target: str, message: str) -> LogMessage:
    return LogMessage(
        timestamp=utc_now(),
        level="error",
        tool="Hook",
        target=target,
        message=message,
    )


def _append_operational_log(message: LogMessage) -> None:
    DEFAULT_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = f"{format_message(message)}\n".encode()
    if not DEFAULT_LOG_PATH.exists() or DEFAULT_LOG_PATH.stat().st_size == 0:
        with DEFAULT_LOG_PATH.open("wb") as handle:
            handle.write(BOM_UTF8)
            handle.write(payload)
        return

    with DEFAULT_LOG_PATH.open("ab") as handle:
        handle.write(payload)


def _emit_runtime_error(exc: Exception, payload: dict[str, Any] | None, config: Any | None) -> None:
    message = _error_message("<runtime-error>", RUNTIME_ERROR_NOTIFICATION)
    if config is None:
        return
    try:
        dispatch_message(message, config.terminal)
    except Exception as dispatch_exc:
        get_logger(LogKind.Operational).warning(
            "Runtime error notification dispatch failed",
            extra={
                "event_type": _event_type(payload),
                "reason": str(dispatch_exc),
            },
        )


if __name__ == "__main__":
    raise SystemExit(main())
