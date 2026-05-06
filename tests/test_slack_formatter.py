from datetime import UTC, datetime

import pytest

from funhou_hook import ApprovalMessage, LogMessage, SummaryMessage
from funhou_hook.slack_formatter import (
    TARGET_TRUNCATE_HEAD,
    TARGET_TRUNCATE_LIMIT,
    TARGET_TRUNCATE_TAIL,
    build_slack_payload,
)


def test_build_slack_payload_renders_log_message_as_single_line_text() -> None:
    message = LogMessage(
        timestamp=datetime(2026, 4, 9, 10, 3, tzinfo=UTC),
        level="info",
        tool="Read",
        target="src/config.ts",
        message="Read src/config.ts",
    )

    payload = build_slack_payload(message)

    assert payload == {"text": "🔹 *Read* `src/config.ts`"}


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


def test_build_slack_payload_renders_multiline_log_target_as_code_block() -> None:
    message = LogMessage(
        timestamp=datetime(2026, 4, 9, 10, 7, tzinfo=UTC),
        level="warning",
        tool="Bash",
        target="npm test\nnpm run lint",
        message="Bash npm test\nnpm run lint",
    )

    payload = build_slack_payload(message)

    assert payload == {"text": "⚠️ *Bash*\n```npm test\nnpm run lint```"}


def test_build_slack_payload_does_not_repeat_target_in_log_detail() -> None:
    message = LogMessage(
        timestamp=datetime(2026, 4, 9, 10, 7, tzinfo=UTC),
        level="info",
        tool="Bash",
        target="npm test",
        message="Completed Bash npm test",
    )

    payload = build_slack_payload(message)

    assert payload == {"text": "🔹 *Bash* `npm test` Completed"}


def test_build_slack_payload_truncates_long_single_line_target() -> None:
    target = "a" * (TARGET_TRUNCATE_LIMIT + 1)
    message = LogMessage(
        timestamp=datetime(2026, 4, 9, 10, 7, tzinfo=UTC),
        level="warning",
        tool="TodoWrite",
        target=target,
        message=f"TodoWrite {target}",
    )

    payload = build_slack_payload(message)

    omitted_count = len(target) - TARGET_TRUNCATE_HEAD - TARGET_TRUNCATE_TAIL
    expected_target = (
        f"{target[:TARGET_TRUNCATE_HEAD]}"
        f"\n（中略：{omitted_count}文字）\n"
        f"{target[-TARGET_TRUNCATE_TAIL:]}"
    )
    assert payload == {"text": f"⚠️ *TodoWrite*\n```{expected_target}```"}


def test_build_slack_payload_truncates_long_multiline_target_inside_code_block() -> None:
    target = f"{'a' * TARGET_TRUNCATE_HEAD}\n{'b' * TARGET_TRUNCATE_LIMIT}"
    message = LogMessage(
        timestamp=datetime(2026, 4, 9, 10, 7, tzinfo=UTC),
        level="warning",
        tool="Bash",
        target=target,
        message=f"Bash {target}",
    )

    payload = build_slack_payload(message)

    omitted_count = len(target) - TARGET_TRUNCATE_HEAD - TARGET_TRUNCATE_TAIL
    expected_target = (
        f"{target[:TARGET_TRUNCATE_HEAD]}"
        f"\n（中略：{omitted_count}文字）\n"
        f"{target[-TARGET_TRUNCATE_TAIL:]}"
    )
    assert payload == {"text": f"⚠️ *Bash*\n```{expected_target}```"}


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
        "@you ⚡ 承認待ち: 本番DBへのマイグレーション実行 "
        "(操作: Bash)"
    )
    assert payload["blocks"] == [
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": "@you ⚡ *承認待ち*"},
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    "*理由:* 本番DBへのマイグレーション実行\n"
                    "*操作:* `Bash`"
                ),
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

    assert payload == {"text": "🔹 *Read* `src/config.ts`"}


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

    assert payload == {"text": "🚨 *Hook* `src/config.ts` Hook runtime error"}


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
        "⚡ 承認待ち: 本番DBへのマイグレーション実行 "
        "(操作: Bash)"
    )
    assert payload["blocks"][0] == {
        "type": "section",
        "text": {"type": "mrkdwn", "text": "⚡ *承認待ち*"},
    }


def test_build_slack_payload_rejects_unknown_message_types() -> None:
    with pytest.raises(TypeError, match="Unsupported message type: object"):
        build_slack_payload(object())
