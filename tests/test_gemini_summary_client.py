from __future__ import annotations

import json
from urllib.request import Request

import pytest

from funhou_hook.gemini_summary_client import GeminiSummaryClient
from funhou_hook.summary_engine import SummaryGenerationError


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
                        "content": {
                            "parts": [
                                {
                                    "text": (
                                        '{"message":"Tests passed.",'
                                        '"next":"Run the manual Slack check."}'
                                    )
                                }
                            ]
                        }
                    }
                ]
            }
        )

    monkeypatch.setattr("funhou_hook.gemini_summary_client._open_request", fake_open)
    client = GeminiSummaryClient(api_key="key-123", model="gemini-2.0-flash", timeout=3.5)

    result = client.generate_summary("Summarize this log")

    assert result == '{"message":"Tests passed.","next":"Run the manual Slack check."}'
    assert "models/gemini-2.0-flash:generateContent?key=key-123" in str(captured["url"])
    assert captured["timeout"] == 3.5
    payload = captured["payload"]
    assert isinstance(payload, dict)
    assert payload["contents"] == [{"parts": [{"text": "Summarize this log"}]}]
    assert payload["generationConfig"] == {
        "temperature": 0.2,
        "maxOutputTokens": 512,
        "responseMimeType": "application/json",
    }

def test_gemini_summary_client_requires_api_key() -> None:
    client = GeminiSummaryClient(api_key=None, model="gemini-2.0-flash", timeout=3.5)

    with pytest.raises(SummaryGenerationError, match="API key"):
        client.generate_summary("prompt")


def test_gemini_summary_client_rejects_missing_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "funhou_hook.gemini_summary_client._open_request",
        lambda request, timeout: FakeResponse({"candidates": [{"content": {"parts": []}}]}),
    )
    client = GeminiSummaryClient(api_key="key-123", model="gemini-2.0-flash", timeout=3.5)

    with pytest.raises(SummaryGenerationError, match="no text"):
        client.generate_summary("prompt")
