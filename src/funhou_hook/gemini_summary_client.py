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
DEFAULT_MAX_OUTPUT_TOKENS = 512
DEFAULT_THINKING_BUDGET = 0
MAX_ERROR_BODY_CHARS = 200
SYSTEM_INSTRUCTION = """\
あなたはAIエージェントの作業分報を要約するアシスタントです。
人間が後追いで状況を把握し、必要なら次の判断をできるようにしてください。
"""
PROMPT_TEMPLATE = """\
入力には直近ターンのログと、サマリー生成の発火元イベントが含まれます。

JSON 出力ルール:
- JSON オブジェクトだけを返す
- JSON の形式は {{"message": "...", "next": "..."}} とする
- 要約に値しない場合は message と next を空文字列にする
- message は1〜2文で、何をしたかと結果を具体的に書く
- next は次に人間またはエージェントが取る行動を書く。不明なら空文字列にする

発火元イベント: {trigger}

ログ:
{logs}
"""
SUMMARY_RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "message": {
            "type": "string",
            "description": "1-2 sentence Japanese summary. Empty when no summary is needed.",
        },
        "next": {
            "type": "string",
            "description": "Next action in Japanese. Empty when unknown or no summary is needed.",
        },
    },
    "required": ["message", "next"],
    "additionalProperties": False,
    "propertyOrdering": ["message", "next"],
}


class GeminiSummaryError(SummaryGenerationError):
    """Classified Gemini provider failure."""

    def __init__(
        self,
        message: str,
        *,
        kind: str,
        retryable: bool = False,
        metadata: dict[str, object] | None = None,
    ) -> None:
        super().__init__(message)
        self.kind = kind
        self.retryable = retryable
        self.metadata = metadata or {}

    def __str__(self) -> str:
        return f"{self.kind}: {super().__str__()}"


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
        max_output_tokens: int = DEFAULT_MAX_OUTPUT_TOKENS,
        thinking_budget: int | None = DEFAULT_THINKING_BUDGET,
        endpoint: str = DEFAULT_GEMINI_ENDPOINT,
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
        self.max_output_tokens = max_output_tokens
        self.thinking_budget = thinking_budget
        self.endpoint = endpoint.rstrip("/")

    def generate_summary(self, prompt: str) -> str:
        """Generate raw model output for a prepared summary prompt."""

        if not self.api_key:
            raise GeminiSummaryError(
                "Gemini API key is not configured.",
                kind="configuration",
                retryable=False,
            )

        payload = {
            "system_instruction": {"parts": [{"text": SYSTEM_INSTRUCTION}]},
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": _build_generation_config(
                max_output_tokens=self.max_output_tokens,
                thinking_budget=self.thinking_budget,
            ),
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
        max_output_tokens: int = DEFAULT_MAX_OUTPUT_TOKENS,
        thinking_budget: int | None = DEFAULT_THINKING_BUDGET,
        endpoint: str = DEFAULT_GEMINI_ENDPOINT,
        client: GeminiSummaryClient | None = None,
    ) -> None:
        self.client = client or GeminiSummaryClient(
            api_key=api_key,
            model=model,
            timeout=timeout,
            max_output_tokens=max_output_tokens,
            thinking_budget=thinking_budget,
            endpoint=endpoint,
        )

    def generate_summary(self, source: SummarySource, *, trigger: str) -> SummaryProviderResult:
        """Generate a summary result using the Gemini client."""

        try:
            raw = _generate_with_retry(
                self.client, build_summary_prompt(source.text, trigger=trigger)
            )
            parsed = parse_summary_output(raw)
        except GeminiSummaryError as exc:
            return SummaryProviderResult.failed(
                reason=str(exc),
                error_kind=exc.kind,
                retryable=exc.retryable,
                metadata=exc.metadata,
            )
        except SummaryGenerationError as exc:
            return SummaryProviderResult.failed(
                reason=str(exc),
                error_kind="summary_generation",
                retryable=False,
            )

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
        raise GeminiSummaryError(
            "Summary model returned invalid JSON "
            f"(message={exc.msg!r}, line={exc.lineno}, col={exc.colno}, "
            f"pos={exc.pos}, length={len(text)}).",
            kind="output_validation",
            retryable=False,
        ) from exc

    if not isinstance(parsed, dict):
        raise GeminiSummaryError(
            "Summary model returned a non-object JSON value.",
            kind="output_validation",
            retryable=False,
        )

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
        except GeminiSummaryError as exc:
            if not exc.retryable or attempt == attempts - 1:
                raise exc
        except Exception as exc:
            raise GeminiSummaryError(
                "Unexpected Gemini summary provider failure.",
                kind="unexpected",
                retryable=False,
            ) from exc
    raise AssertionError("unreachable")


def _build_generation_config(
    *,
    max_output_tokens: int,
    thinking_budget: int | None,
) -> dict[str, Any]:
    config: dict[str, Any] = {
        "temperature": 0.2,
        "maxOutputTokens": max_output_tokens,
        "responseMimeType": "application/json",
        "responseJsonSchema": SUMMARY_RESPONSE_SCHEMA,
    }
    if thinking_budget is not None:
        config["thinkingConfig"] = {"thinkingBudget": thinking_budget}
    return config


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
        status = exc.code
        body = _truncate_body(_decode_body(exc.read()))
        raise GeminiSummaryError(
            f"Gemini API returned HTTP {status}: {body}",
            kind="http_error",
            retryable=status == 429 or status >= 500,
            metadata={"status": status},
        ) from exc
    except (OSError, TimeoutError, URLError) as exc:
        raise GeminiSummaryError(
            "Gemini API request failed.",
            kind="transport_error",
            retryable=True,
            metadata={"error_type": type(exc).__name__},
        ) from exc

    try:
        parsed = json.loads(_decode_body(raw_body))
    except json.JSONDecodeError as exc:
        raise GeminiSummaryError(
            "Gemini API returned invalid JSON.",
            kind="invalid_response_json",
            retryable=False,
        ) from exc
    if not isinstance(parsed, dict):
        raise GeminiSummaryError(
            "Gemini API returned a non-object JSON value.",
            kind="invalid_response_shape",
            retryable=False,
        )
    return parsed


def _open_request(request: Request, timeout: float) -> Any:
    return urlopen(request, timeout=timeout)


def _extract_text(response: dict[str, Any]) -> str:
    candidates = response.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        raise GeminiSummaryError(
            "Gemini API returned no candidates.",
            kind="missing_candidates",
            retryable=True,
            metadata=_response_metadata(response),
        )

    candidate = candidates[0]
    if not isinstance(candidate, dict):
        raise GeminiSummaryError(
            "Gemini API returned a non-object candidate.",
            kind="invalid_candidate",
            retryable=False,
            metadata=_response_metadata(response),
        )

    finish_reason = candidate.get("finishReason")
    if finish_reason is not None and finish_reason != "STOP":
        raise GeminiSummaryError(
            f"Gemini API finished without usable text: {finish_reason}",
            kind="generation_incomplete",
            retryable=False,
            metadata={**_response_metadata(response), "finish_reason": str(finish_reason)},
        )

    content = candidate.get("content")
    if not isinstance(content, dict):
        raise GeminiSummaryError(
            "Gemini API returned a candidate without content.",
            kind="missing_content",
            retryable=finish_reason is None,
            metadata={**_response_metadata(response), "finish_reason": str(finish_reason)},
        )

    parts = content.get("parts")
    if not isinstance(parts, list):
        raise GeminiSummaryError(
            "Gemini API returned content without parts.",
            kind="missing_parts",
            retryable=finish_reason is None,
            metadata={**_response_metadata(response), "finish_reason": str(finish_reason)},
        )

    texts = [part.get("text") for part in parts if isinstance(part, dict) and part.get("text")]
    if not texts:
        raise GeminiSummaryError(
            "Gemini API returned no text.",
            kind="missing_text",
            retryable=finish_reason is None,
            metadata={**_response_metadata(response), "finish_reason": str(finish_reason)},
        )
    return "\n".join(str(text) for text in texts)


def _response_metadata(response: dict[str, Any]) -> dict[str, object]:
    metadata: dict[str, object] = {"candidate_count": 0}
    candidates = response.get("candidates")
    if isinstance(candidates, list):
        metadata["candidate_count"] = len(candidates)
    usage = response.get("usageMetadata")
    if isinstance(usage, dict):
        for key in (
            "promptTokenCount",
            "candidatesTokenCount",
            "thoughtsTokenCount",
            "totalTokenCount",
        ):
            if key in usage:
                metadata[key] = usage[key]
    return metadata


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
