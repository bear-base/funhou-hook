from datetime import UTC, datetime
from urllib.error import URLError

import pytest

from funhou_hook.config import SlackChannelConfig
from funhou_hook.messages import LogMessage
from funhou_hook.slack_sender import SlackDeliveryError, send_slack_message


class FakeResponse:
    def __init__(self, status: int, body: bytes = b"ok") -> None:
        self.status = status
        self._body = body

    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self) -> bytes:
        return self._body


def _message(level: str = "info") -> LogMessage:
    return LogMessage(
        timestamp=datetime(2026, 4, 9, 10, 3, tzinfo=UTC),
        level=level,
        tool="Read",
        target="src/config.ts",
        message="Read src/config.ts",
    )


def test_send_slack_message_posts_json_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def fake_open(request: object, timeout: float) -> FakeResponse:
        captured["request"] = request
        captured["timeout"] = timeout
        return FakeResponse(status=200)

    monkeypatch.setattr("funhou_hook.slack_sender._open_request", fake_open)
    config = SlackChannelConfig(
        enabled=True,
        webhook="https://hooks.slack.com/services/T000/B000/XXXX",
    )

    send_slack_message(_message(), config)

    request = captured["request"]
    assert request.full_url == "https://hooks.slack.com/services/T000/B000/XXXX"
    assert request.get_method() == "POST"
    assert request.headers["Content-type"] == "application/json; charset=utf-8"
    assert request.headers["User-agent"] == "funhou-hook"
    assert request.data == '{"text":"ℹ️ *Read* `src/config.ts`"}'.encode()
    assert captured["timeout"] == 5.0


def test_send_slack_message_applies_mention_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def fake_open(request: object, timeout: float) -> FakeResponse:
        captured["body"] = request.data
        return FakeResponse(status=200)

    monkeypatch.setattr("funhou_hook.slack_sender._open_request", fake_open)
    config = SlackChannelConfig(
        enabled=True,
        webhook="https://hooks.slack.com/services/T000/B000/XXXX",
        mention_on=("warning", "danger"),
        mention_to="@you",
    )

    send_slack_message(_message(level="warning"), config)

    assert captured["body"] == '{"text":"@you ⚠️ *Read* `src/config.ts`"}'.encode()


def test_send_slack_message_wraps_http_status_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_open(request: object, timeout: float) -> FakeResponse:
        return FakeResponse(status=500, body=b"temporarily unavailable")

    monkeypatch.setattr("funhou_hook.slack_sender._open_request", fake_open)
    config = SlackChannelConfig(
        enabled=True,
        webhook="https://hooks.slack.com/services/T000/B000/XXXX",
    )

    with pytest.raises(SlackDeliveryError) as exc_info:
        send_slack_message(_message(), config)

    assert exc_info.value.status_code == 500
    assert exc_info.value.response_body == "temporarily unavailable"
    assert "Slack webhook returned HTTP 500" in str(exc_info.value)


def test_send_slack_message_truncates_http_error_body(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_open(request: object, timeout: float) -> FakeResponse:
        return FakeResponse(status=400, body=b"x" * 300)

    monkeypatch.setattr("funhou_hook.slack_sender._open_request", fake_open)
    config = SlackChannelConfig(
        enabled=True,
        webhook="https://hooks.slack.com/services/T000/B000/XXXX",
    )

    with pytest.raises(SlackDeliveryError) as exc_info:
        send_slack_message(_message(), config)

    assert exc_info.value.status_code == 400
    assert exc_info.value.response_body == ("x" * 200)


def test_send_slack_message_wraps_network_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = URLError("network unreachable")

    def fake_open(request: object, timeout: float) -> FakeResponse:
        raise original

    monkeypatch.setattr("funhou_hook.slack_sender._open_request", fake_open)
    config = SlackChannelConfig(
        enabled=True,
        webhook="https://hooks.slack.com/services/T000/B000/XXXX",
    )

    with pytest.raises(SlackDeliveryError) as exc_info:
        send_slack_message(_message(), config)

    assert exc_info.value.status_code is None
    assert exc_info.value.response_body is None
    assert exc_info.value.original is original
    assert "Slack webhook request failed" in str(exc_info.value)


def test_send_slack_message_rejects_missing_webhook() -> None:
    config = SlackChannelConfig(enabled=True, webhook=None)

    with pytest.raises(SlackDeliveryError) as exc_info:
        send_slack_message(_message(), config)

    assert "Slack webhook is not configured" in str(exc_info.value)
