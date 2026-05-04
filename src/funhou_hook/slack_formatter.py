"""Slack payload formatting for funhou messages."""

from __future__ import annotations

from datetime import timedelta

from .messages import ApprovalMessage, FunhouMessage, Level, LogMessage, SummaryMessage

LEVEL_ICONS: dict[Level, str] = {
    "info": "🔹",
    "warning": "⚠️",
    "danger": "⚡",
    "error": "🚨",
}


def build_slack_payload(
    message: FunhouMessage,
    mention_to: str | None = None,
    mention_levels: set[Level] = frozenset(),
) -> dict:
    """Convert a funhou message into a Slack Incoming Webhook payload."""

    if isinstance(message, LogMessage):
        return _build_log_payload(message, mention_to=mention_to, mention_levels=mention_levels)
    if isinstance(message, SummaryMessage):
        return _build_summary_payload(message)
    if isinstance(message, ApprovalMessage):
        return _build_approval_payload(
            message,
            mention_to=mention_to,
            mention_levels=mention_levels,
        )
    raise TypeError(f"Unsupported message type: {type(message).__name__}")


def _build_log_payload(
    message: LogMessage,
    *,
    mention_to: str | None,
    mention_levels: set[Level],
) -> dict:
    icon = LEVEL_ICONS[message.level]
    body = _format_log_body(message)
    detail = _format_log_detail(message)
    text = _prefix_mention(
        f"{icon} {body}{detail}",
        level=message.level,
        mention_to=mention_to,
        mention_levels=mention_levels,
    )
    return {"text": text}


def _format_log_body(message: LogMessage) -> str:
    if _is_multiline(message.target):
        return f"*{message.tool}*\n```{message.target}```"
    return f"*{message.tool}* `{message.target}`"


def _format_log_detail(message: LogMessage) -> str:
    default_message = f"{message.tool} {message.target}"
    detail = _remove_repeated_target(message.message, default_message)
    if not detail:
        return ""
    return f" {detail}"


def _remove_repeated_target(message: str, default_message: str) -> str:
    if not message or message == default_message:
        return ""

    replacements = (
        (f"Completed {default_message}", "Completed"),
        (f"Approval granted: {default_message}", "Approval granted"),
        (f"Approval denied: {default_message}", "Approval denied"),
        (f"Denied: {default_message}", "Denied"),
        (f"Failed {default_message}: ", "Failed: "),
    )
    for prefix, replacement in replacements:
        if message == prefix:
            return replacement
        if message.startswith(prefix):
            return f"{replacement}{message.removeprefix(prefix)}"
    return message


def _is_multiline(value: str) -> bool:
    return "\n" in value or "\r" in value


def _build_summary_payload(message: SummaryMessage) -> dict:
    start_time = _format_summary_start(message)
    end_time = message.timestamp.strftime("%H:%M")
    title = f"📋 {start_time}-{end_time} まとめ"
    text = f"{title}\n{message.message}\n次: {message.next}"
    return {
        "text": text,
        "blocks": [
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": title},
            },
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": message.message},
            },
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"次: {message.next}"},
            },
        ],
    }


def _build_approval_payload(
    message: ApprovalMessage,
    *,
    mention_to: str | None,
    mention_levels: set[Level],
) -> dict:
    title = _prefix_mention(
        "⚡ 承認待ち",
        level=message.level,
        mention_to=mention_to,
        mention_levels=mention_levels,
    )
    text = f"{title}: {message.reason} ({message.tool} {message.command})"
    return {
        "text": text,
        "blocks": [
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": _format_approval_heading(title)},
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*理由:* {message.reason}\n*コマンド:* `{message.command}`",
                },
            },
        ],
    }


def _prefix_mention(
    text: str,
    *,
    level: Level,
    mention_to: str | None,
    mention_levels: set[Level],
) -> str:
    if not mention_to or level not in mention_levels:
        return text
    return f"{mention_to} {text}"


def _format_approval_heading(title: str) -> str:
    if title.startswith("⚡ "):
        return title.replace("⚡ 承認待ち", "⚡ *承認待ち*", 1)
    return title.replace("承認待ち", "*承認待ち*", 1)


def _format_summary_start(message: SummaryMessage) -> str:
    start = message.timestamp - timedelta(seconds=message.duration_sec)
    return start.strftime("%H:%M")
