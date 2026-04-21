"""Slack payload formatting for funhou messages."""

from __future__ import annotations

from datetime import timedelta

from .messages import ApprovalMessage, FunhouMessage, Level, LogMessage, SummaryMessage

LOG_ICONS: dict[str, str] = {
    "Read": "📄",
    "Bash": "🔨",
}
LEVEL_ICONS: dict[Level, str] = {
    "info": "ℹ️",
    "warning": "⚠️",
    "danger": "🔴",
    "error": "❌",
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
    icon = LOG_ICONS.get(message.tool, LEVEL_ICONS[message.level])
    text = _prefix_mention(
        f"{icon} {message.message}",
        level=message.level,
        mention_to=mention_to,
        mention_levels=mention_levels,
    )
    return {"text": text}


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
    prefix = _prefix_mention(
        "🔴 承認待ち",
        level=message.level,
        mention_to=mention_to,
        mention_levels=mention_levels,
    )
    text = f"{prefix}: {message.reason} ({message.tool} {message.command})"
    return {
        "text": text,
        "blocks": [
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"{prefix.replace(' 承認待ち', ' *承認待ち*')}"},
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*理由:* {message.reason}\n*コマンド:* `{message.command}`",
                },
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "Slack上では承認できません。Phase 3 までは別経路で判断してください。",
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
    if mention_to is None or level not in mention_levels:
        return text
    return f"{mention_to} {text}"


def _format_summary_start(message: SummaryMessage) -> str:
    start = message.timestamp - timedelta(seconds=message.duration_sec)
    return start.strftime("%H:%M")
