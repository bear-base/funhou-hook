from datetime import UTC, datetime

import pytest

from funhou_hook import ApprovalMessage, LogMessage, SummaryMessage
from funhou_hook.slack_formatter import build_slack_payload


def test_build_slack_payload_renders_log_message_as_single_line_text() -> None:
    message = LogMessage(
        timestamp=datetime(2026, 4, 9, 10, 3, tzinfo=UTC),
        level="info",
        tool="Read",
        target="src/config.ts",
        message="Read src/config.ts",
    )

    payload = build_slack_payload(message)

    assert payload == {"text": "ℹ️ *Read* `src/config.ts`"}


def test_build_slack_payload_prefixes_mentions_for_matching_log_levels() -> None:
    message = LogMessage(
        timestamp=datetime(2026, 4, 9, 10, 7, tzinfo=UTC),
        level="warning",
        tool="Bash",
        target="npm run build",
        message="Bash npm run build",
    )

    payload = build_slack_payload(
        message,
        mention_to="@you",
        mention_levels={"warning", "danger"},
    )

    assert payload == {"text": "@you ⚠️ *Bash* `npm run build`"}


def test_build_slack_payload_renders_summary_message_as_blocks() -> None:
    message = SummaryMessage(
        timestamp=datetime(2026, 4, 9, 10, 15, tzinfo=UTC),
        message="config.tsのDB接続設定を変更し、テスト24件が通過。",
        next="マイグレーション実行（承認待ち）",
        log_count=12,
        duration_sec=720,
    )

    payload = build_slack_payload(message)

    assert payload["text"] == (
        "📋 10:03-10:15 まとめ\n"
        "config.tsのDB接続設定を変更し、テスト24件が通過。\n"
        "次: マイグレーション実行（承認待ち）"
    )
    assert payload["blocks"] == [
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": "📋 10:03-10:15 まとめ"},
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "config.tsのDB接続設定を変更し、テスト24件が通過。",
            },
        },
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": "次: マイグレーション実行（承認待ち）"},
        },
    ]


def test_build_slack_payload_renders_approval_message_with_mention_and_blocks() -> None:
    message = ApprovalMessage(
        timestamp=datetime(2026, 4, 9, 10, 16, tzinfo=UTC),
        level="danger",
        tool="Bash",
        command="npx prisma migrate deploy",
        reason="本番DBへのマイグレーション実行",
    )

    payload = build_slack_payload(
        message,
        mention_to="@you",
        mention_levels={"danger"},
    )

    assert payload["text"] == (
        "@you 🔴 承認待ち: 本番DBへのマイグレーション実行 "
        "(Bash npx prisma migrate deploy)"
    )
    assert payload["blocks"] == [
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": "@you 🔴 *承認待ち*"},
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    "*理由:* 本番DBへのマイグレーション実行\n"
                    "*コマンド:* `npx prisma migrate deploy`"
                ),
            },
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "Slack上では承認できません。Phase 3 までは別経路で判断してください。",
            },
        },
    ]


def test_build_slack_payload_does_not_add_mention_when_level_is_not_selected() -> None:
    message = LogMessage(
        timestamp=datetime(2026, 4, 9, 10, 3, tzinfo=UTC),
        level="info",
        tool="Read",
        target="src/config.ts",
        message="Read src/config.ts",
    )

    payload = build_slack_payload(
        message,
        mention_to="@you",
        mention_levels={"warning", "danger"},
    )

    assert payload == {"text": "ℹ️ *Read* `src/config.ts`"}


def test_build_slack_payload_does_not_add_mention_when_mention_target_is_missing() -> None:
    message = LogMessage(
        timestamp=datetime(2026, 4, 9, 10, 7, tzinfo=UTC),
        level="warning",
        tool="Bash",
        target="npm run build",
        message="Bash npm run build",
    )

    payload = build_slack_payload(
        message,
        mention_to=None,
        mention_levels={"warning", "danger"},
    )

    assert payload == {"text": "⚠️ *Bash* `npm run build`"}


def test_build_slack_payload_uses_level_icon_for_unknown_tool_names() -> None:
    message = LogMessage(
        timestamp=datetime(2026, 4, 9, 10, 8, tzinfo=UTC),
        level="error",
        tool="Hook",
        target="src/config.ts",
        message="Hook runtime error",
    )

    payload = build_slack_payload(message)

    assert payload == {"text": "❌ *Hook* `src/config.ts` Hook runtime error"}


def test_build_slack_payload_renders_approval_without_mention_when_not_requested() -> None:
    message = ApprovalMessage(
        timestamp=datetime(2026, 4, 9, 10, 16, tzinfo=UTC),
        level="danger",
        tool="Bash",
        command="npx prisma migrate deploy",
        reason="本番DBへのマイグレーション実行",
    )

    payload = build_slack_payload(message)

    assert payload["text"] == (
        "🔴 承認待ち: 本番DBへのマイグレーション実行 "
        "(Bash npx prisma migrate deploy)"
    )
    assert payload["blocks"][0] == {
        "type": "section",
        "text": {"type": "mrkdwn", "text": "🔴 *承認待ち*"},
    }


def test_build_slack_payload_rejects_unknown_message_types() -> None:
    with pytest.raises(TypeError, match="Unsupported message type: object"):
        build_slack_payload(object())
