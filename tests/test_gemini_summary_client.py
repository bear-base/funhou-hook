from __future__ import annotations

import json
from urllib.request import Request

import pytest

from funhou_hook.gemini_summary_client import (
    GeminiSummaryClient,
    GeminiSummaryError,
    GeminiSummaryProvider,
    build_summary_prompt,
    parse_summary_output,
)
from funhou_hook.summary_engine import SummaryGenerationError, SummarySource


class FakeResponse:
    def __init__(self, body: dict[str, object]) -> None:
        self.body = json.dumps(body).encode("utf-8")

    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self) -> bytes:
        return self.body


def test_gemini_summary_client_posts_generate_content_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def fake_open(request: Request, timeout: float) -> FakeResponse:
        captured["url"] = request.full_url
        captured["timeout"] = timeout
        captured["headers"] = dict(request.header_items())
        captured["payload"] = json.loads(request.data.decode("utf-8"))  # type: ignore[union-attr]
        return FakeResponse(
            {
                "candidates": [
                    {
                        "finishReason": "STOP",
                        "content": {
                            "parts": [
                                {
                                    "text": (
                                        '{"message":"Tests passed.",'
                                        '"next":"Run the manual Slack check."}'
                                    )
                                }
                            ]
                        },
                    }
                ]
            }
        )

    monkeypatch.setattr("funhou_hook.gemini_summary_client._open_request", fake_open)
    client = GeminiSummaryClient(
        api_key="key-123",
        model="gemini-2.5-flash-lite",
        timeout=3.5,
        max_output_tokens=768,
        thinking_budget=0,
    )

    result = client.generate_summary("Summarize this log")

    assert result == '{"message":"Tests passed.","next":"Run the manual Slack check."}'
    assert "models/gemini-2.5-flash-lite:generateContent?key=key-123" in str(captured["url"])
    assert captured["timeout"] == 3.5
    payload = captured["payload"]
    assert isinstance(payload, dict)
    system_text = payload["system_instruction"]["parts"][0]["text"]
    assert "AIエージェントの作業分報を要約するアシスタント" in system_text
    assert "人間が後追いで状況を把握" in system_text
    assert payload["contents"] == [{"parts": [{"text": "Summarize this log"}]}]
    generation_config = payload["generationConfig"]
    assert generation_config["temperature"] == 0.2
    assert generation_config["maxOutputTokens"] == 768
    assert generation_config["responseMimeType"] == "application/json"
    assert generation_config["thinkingConfig"] == {"thinkingBudget": 0}
    assert generation_config["responseJsonSchema"]["required"] == ["message", "next"]


def test_gemini_summary_client_requires_api_key() -> None:
    client = GeminiSummaryClient(api_key=None, model="gemini-2.0-flash", timeout=3.5)

    with pytest.raises(SummaryGenerationError, match="API key"):
        client.generate_summary("prompt")


def test_gemini_summary_client_rejects_missing_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "funhou_hook.gemini_summary_client._open_request",
        lambda request, timeout: FakeResponse(
            {"candidates": [{"finishReason": "STOP", "content": {"parts": []}}]}
        ),
    )
    client = GeminiSummaryClient(api_key="key-123", model="gemini-2.0-flash", timeout=3.5)

    with pytest.raises(SummaryGenerationError, match="no text"):
        client.generate_summary("prompt")


def test_gemini_summary_client_omits_thinking_config_when_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def fake_open(request: Request, timeout: float) -> FakeResponse:
        captured["payload"] = json.loads(request.data.decode("utf-8"))  # type: ignore[union-attr]
        return FakeResponse(
            {
                "candidates": [
                    {
                        "finishReason": "STOP",
                        "content": {"parts": [{"text": '{"message":"","next":""}'}]},
                    }
                ]
            }
        )

    monkeypatch.setattr("funhou_hook.gemini_summary_client._open_request", fake_open)
    client = GeminiSummaryClient(
        api_key="key-123",
        model="gemini-2.0-flash",
        timeout=3.5,
        thinking_budget=None,
    )

    client.generate_summary("prompt")

    payload = captured["payload"]
    assert isinstance(payload, dict)
    assert "thinkingConfig" not in payload["generationConfig"]


def test_gemini_summary_client_classifies_incomplete_generation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "funhou_hook.gemini_summary_client._open_request",
        lambda request, timeout: FakeResponse(
            {
                "candidates": [{"finishReason": "MAX_TOKENS", "content": {"parts": []}}],
                "usageMetadata": {"totalTokenCount": 123, "thoughtsTokenCount": 40},
            }
        ),
    )
    client = GeminiSummaryClient(api_key="key-123", model="gemini-2.5-flash-lite", timeout=3.5)

    with pytest.raises(GeminiSummaryError) as exc_info:
        client.generate_summary("prompt")

    assert exc_info.value.kind == "generation_incomplete"
    assert exc_info.value.retryable is False
    assert exc_info.value.metadata["finish_reason"] == "MAX_TOKENS"
    assert exc_info.value.metadata["thoughtsTokenCount"] == 40


def test_gemini_summary_provider_retries_retryable_client_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    def fake_summary(prompt: str) -> str:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise GeminiSummaryError(
                "temporary transport failure",
                kind="transport_error",
                retryable=True,
            )
        return '{"message":"Retried successfully.","next":""}'

    client = GeminiSummaryClient(api_key="key-123", model="gemini-2.5-flash-lite", timeout=3.5)
    monkeypatch.setattr(client, "generate_summary", fake_summary)
    provider = GeminiSummaryProvider(
        api_key="key-123",
        model="gemini-2.5-flash-lite",
        timeout=3.5,
        client=client,
    )

    result = provider.generate_summary(
        SummarySource(text="10:00 [WARN] Bash: npm run build", offset=42, log_count=1),
        trigger="Stop",
    )

    assert calls == 2
    assert result.status == "generated"
    assert result.message == "Retried successfully."


def test_gemini_summary_provider_does_not_retry_non_retryable_client_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    def fake_summary(prompt: str) -> str:
        nonlocal calls
        calls += 1
        raise GeminiSummaryError("bad config", kind="configuration", retryable=False)

    client = GeminiSummaryClient(api_key="key-123", model="gemini-2.5-flash-lite", timeout=3.5)
    monkeypatch.setattr(client, "generate_summary", fake_summary)
    provider = GeminiSummaryProvider(
        api_key="key-123",
        model="gemini-2.5-flash-lite",
        timeout=3.5,
        client=client,
    )

    result = provider.generate_summary(
        SummarySource(text="10:00 [WARN] Bash: npm run build", offset=42, log_count=1),
        trigger="Stop",
    )

    assert calls == 1
    assert result.status == "failed"
    assert "configuration" in str(result.reason)


def test_gemini_summary_provider_returns_generated_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prompts: list[str] = []

    def fake_summary(prompt: str) -> str:
        prompts.append(prompt)
        return '{"message":"Tests passed.","next":"Run the manual Slack check."}'

    client = GeminiSummaryClient(api_key="key-123", model="gemini-2.0-flash", timeout=3.5)
    monkeypatch.setattr(client, "generate_summary", fake_summary)
    provider = GeminiSummaryProvider(
        api_key="key-123",
        model="gemini-2.0-flash",
        timeout=3.5,
        client=client,
    )

    result = provider.generate_summary(
        SummarySource(text="10:00 [INFO] Bash: tests passed", offset=42, log_count=1),
        trigger="Stop",
    )

    assert result.status == "generated"
    assert result.message == "Tests passed."
    assert result.next == "Run the manual Slack check."
    assert "発火元イベント: Stop" in prompts[0]
    assert "tests passed" in prompts[0]


def test_gemini_summary_provider_returns_skipped_for_empty_summary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = GeminiSummaryClient(api_key="key-123", model="gemini-2.0-flash", timeout=3.5)
    monkeypatch.setattr(client, "generate_summary", lambda prompt: "")
    provider = GeminiSummaryProvider(
        api_key="key-123",
        model="gemini-2.0-flash",
        timeout=3.5,
        client=client,
    )

    result = provider.generate_summary(
        SummarySource(text="10:00 [INFO] Read: src/config.py", offset=42, log_count=1),
        trigger="Stop",
    )

    assert result.status == "skipped"


def test_gemini_summary_provider_returns_failed_for_invalid_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = GeminiSummaryClient(api_key="key-123", model="gemini-2.0-flash", timeout=3.5)
    monkeypatch.setattr(client, "generate_summary", lambda prompt: "not-json")
    provider = GeminiSummaryProvider(
        api_key="key-123",
        model="gemini-2.0-flash",
        timeout=3.5,
        client=client,
    )

    result = provider.generate_summary(
        SummarySource(text="10:00 [WARN] Bash: npm run build", offset=42, log_count=1),
        trigger="PermissionRequest",
    )

    assert result.status == "failed"
    assert "invalid JSON" in str(result.reason)


def test_parse_summary_output_rejects_invalid_json() -> None:
    with pytest.raises(SummaryGenerationError):
        parse_summary_output("not-json")


def test_build_summary_prompt_contains_logs_and_trigger() -> None:
    prompt = build_summary_prompt("10:00 [INFO] Read: Read src/config.py", trigger="Stop")

    assert "発火元イベント: Stop" in prompt
    assert "Read src/config.py" in prompt
