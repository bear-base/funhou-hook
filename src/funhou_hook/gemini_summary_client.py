"""Gemini API adapter for summary generation."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from .summary_engine import SummaryGenerationError, SummaryProviderResult, SummarySource

DEFAULT_GEMINI_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta"
MAX_ERROR_BODY_CHARS = 200
PROMPT_TEMPLATE = """\
あなたはAIエージェントの作業分報を要約するアシスタントです。

入力には直近ターンのログと、サマリー生成の発火元イベントが含まれます。
人間が後追いで状況を把握し、必要なら次の判断をできるようにしてください。

出力ルール:
- 要約に値しない場合は空文字列だけを返す
- 要約する場合は JSON オブジェクトだけを返す
- JSON の形式は {{"message": "...", "next": "..."}} とする
- message は1〜2文で、何をしたかと結果を具体的に書く
- next は次に人間またはエージェントが取る行動を書く。不明なら空文字列にする
- Markdown コードフェンスや前置きは返さない

発火元イベント: {trigger}

ログ:
{logs}
"""


@dataclass(slots=True, frozen=True)
class ParsedSummary:
    message: str
    next: str


class GeminiSummaryClient:
    """Low-level Gemini generateContent client for prepared prompts."""

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
        """Generate raw model output for a prepared summary prompt."""

        if not self.api_key:
            raise SummaryGenerationError("Gemini API key is not configured.")

        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": 0.2,
                "maxOutputTokens": 512,
                "responseMimeType": "application/json",
            },
        }
        response = _post_json(
            _generate_content_url(self.endpoint, self.model, self.api_key),
            payload,
            timeout=self.timeout,
        )
        return _extract_text(response)


class GeminiSummaryProvider:
    """Use-case level summary provider backed by Gemini.

    When ``client`` is provided, the connection settings are ignored and the supplied
    low-level client is used directly. This keeps tests and custom callers explicit.
    """

    def __init__(
        self,
        *,
        api_key: str | None,
        model: str,
        timeout: float,
        endpoint: str = DEFAULT_GEMINI_ENDPOINT,
        client: GeminiSummaryClient | None = None,
    ) -> None:
        self.client = client or GeminiSummaryClient(
            api_key=api_key,
            model=model,
            timeout=timeout,
            endpoint=endpoint,
        )

    def generate_summary(self, source: SummarySource, *, trigger: str) -> SummaryProviderResult:
        """Generate a summary result using the Gemini client."""

        try:
            raw = _generate_with_retry(
                self.client, build_summary_prompt(source.text, trigger=trigger)
            )
            parsed = parse_summary_output(raw)
        except SummaryGenerationError as exc:
            return SummaryProviderResult.failed(reason=str(exc))

        if parsed is None:
            return SummaryProviderResult.skipped(reason="provider returned no summary")
        return SummaryProviderResult.generated(message=parsed.message, next=parsed.next)


def build_summary_prompt(logs: str, *, trigger: str) -> str:
    """Build the prompt sent to Gemini for summary generation."""

    return PROMPT_TEMPLATE.format(trigger=trigger, logs=logs)


def parse_summary_output(raw: str) -> ParsedSummary | None:
    """Parse model output into provider summary fields."""

    text = raw.strip()
    if not text:
        return None
    if text.startswith("```"):
        text = _strip_code_fence(text)

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise SummaryGenerationError(
            "Summary model returned invalid JSON "
            f"(message={exc.msg!r}, line={exc.lineno}, col={exc.colno}, "
            f"pos={exc.pos}, length={len(text)})."
        ) from exc

    if not isinstance(parsed, dict):
        raise SummaryGenerationError("Summary model returned a non-object JSON value.")

    message = str(parsed.get("message") or "").strip()
    next_action = str(parsed.get("next") or "").strip()
    if not message:
        return None
    return ParsedSummary(message=message, next=next_action)


def _generate_with_retry(client: GeminiSummaryClient, prompt: str) -> str:
    attempts = 2
    for attempt in range(attempts):
        try:
            return client.generate_summary(prompt)
        except Exception as exc:
            if attempt == attempts - 1:
                raise SummaryGenerationError("Summary generation failed.") from exc
    raise AssertionError("unreachable")


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

    candidate = candidates[0]
    if not isinstance(candidate, dict):
        raise SummaryGenerationError("Gemini API returned a non-object candidate.")

    content = candidate.get("content")
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


def _strip_code_fence(text: str) -> str:
    lines = text.splitlines()
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].startswith("```"):
        lines = lines[:-1]
    return "\n".join(lines).strip()
