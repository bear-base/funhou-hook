"""Gemini API adapter for summary generation."""

from __future__ import annotations

import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from .summary_engine import SummaryGenerationError

DEFAULT_GEMINI_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta"
MAX_ERROR_BODY_CHARS = 200


class GeminiSummaryClient:
    """SummaryClient implementation backed by Gemini generateContent."""

    def __init__(
        self,
        *,
        api_key: str | None,
        model: str,
        timeout: float,
        endpoint: str = DEFAULT_GEMINI_ENDPOINT,
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
        self.endpoint = endpoint.rstrip("/")

    def generate_summary(self, prompt: str) -> str:
        """Generate a summary using the Gemini generateContent REST API."""

        if not self.api_key:
            raise SummaryGenerationError("Gemini API key is not configured.")

        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": 0.2,
                "maxOutputTokens": 512,
                "response_mime_type": "application/json",
            },
        }
        response = _post_json(
            _generate_content_url(self.endpoint, self.model, self.api_key),
            payload,
            timeout=self.timeout,
        )
        return _extract_text(response)


def _generate_content_url(endpoint: str, model: str, api_key: str) -> str:
    model_path = quote(model, safe="")
    query = urlencode({"key": api_key})
    return f"{endpoint}/models/{model_path}:generateContent?{query}"


def _post_json(url: str, payload: dict[str, Any], *, timeout: float) -> dict[str, Any]:
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    request = Request(
        url,
        data=body,
        headers={
            "Content-Type": "application/json; charset=utf-8",
            "User-Agent": "funhou-hook",
        },
        method="POST",
    )

    try:
        with _open_request(request, timeout) as response:
            raw_body = response.read()
    except HTTPError as exc:
        raise SummaryGenerationError(
            f"Gemini API returned HTTP {exc.code}: {_truncate_body(_decode_body(exc.read()))}"
        ) from exc
    except (OSError, TimeoutError, URLError) as exc:
        raise SummaryGenerationError("Gemini API request failed.") from exc

    try:
        parsed = json.loads(_decode_body(raw_body))
    except json.JSONDecodeError as exc:
        raise SummaryGenerationError("Gemini API returned invalid JSON.") from exc
    if not isinstance(parsed, dict):
        raise SummaryGenerationError("Gemini API returned a non-object JSON value.")
    return parsed


def _open_request(request: Request, timeout: float) -> Any:
    return urlopen(request, timeout=timeout)


def _extract_text(response: dict[str, Any]) -> str:
    candidates = response.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        raise SummaryGenerationError("Gemini API returned no candidates.")

    content = candidates[0].get("content")
    if not isinstance(content, dict):
        raise SummaryGenerationError("Gemini API returned a candidate without content.")

    parts = content.get("parts")
    if not isinstance(parts, list):
        raise SummaryGenerationError("Gemini API returned content without parts.")

    texts = [part.get("text") for part in parts if isinstance(part, dict) and part.get("text")]
    if not texts:
        raise SummaryGenerationError("Gemini API returned no text.")
    return "\n".join(str(text) for text in texts)


def _decode_body(body: bytes) -> str:
    return body.decode("utf-8", errors="replace")


def _truncate_body(body: str) -> str:
    return body[:MAX_ERROR_BODY_CHARS]
