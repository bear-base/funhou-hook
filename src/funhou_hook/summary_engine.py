"""LLM-backed summary generation from the terminal funhou log."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Protocol

from .config import SummaryEngineConfig, TerminalChannelConfig
from .logging import LogKind, get_logger
from .messages import SummaryMessage, utc_now

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


class SummaryClient(Protocol):
    """Minimal interface implemented by LLM summary providers."""

    def generate_summary(self, prompt: str) -> str:
        """Return raw model output for the summary prompt."""


class SummaryGenerationError(Exception):
    """Raised for retryable or reportable summary generation failures."""


@dataclass(slots=True, frozen=True)
class SummarySource:
    """Log slice used as summary input."""

    text: str
    offset: int
    log_count: int


def build_summary_message(
    *,
    trigger: str,
    terminal: TerminalChannelConfig,
    summary: SummaryEngineConfig,
    client: SummaryClient,
    now: datetime | None = None,
) -> SummaryMessage | None:
    """Generate a SummaryMessage from new terminal log content when useful."""

    if not summary.enabled:
        return None

    source = read_summary_source(
        terminal.output,
        summary.state_path,
        max_chars=summary.max_log_chars,
    )
    if source.log_count == 0:
        _save_summary_state(summary.state_path, source.offset)
        return None

    prompt = build_summary_prompt(source.text, trigger=trigger)
    try:
        raw = _generate_with_retry(client, prompt)
        parsed = parse_summary_output(raw)
    except SummaryGenerationError as exc:
        get_logger(LogKind.Debug).warning(
            "Summary generation skipped",
            extra={"trigger": trigger, "reason": str(exc)},
        )
        return None
    if parsed is None:
        _save_summary_state(summary.state_path, source.offset)
        return None

    timestamp = now or utc_now()
    _save_summary_state(summary.state_path, source.offset)
    return SummaryMessage(
        timestamp=timestamp,
        message=parsed.message,
        next=parsed.next,
        log_count=source.log_count,
        duration_sec=0,
        trigger=trigger,
    )


def read_summary_source(log_path: Path, state_path: Path, *, max_chars: int) -> SummarySource:
    """Read new terminal log content after the last stored byte offset."""

    if not log_path.exists():
        return SummarySource(text="", offset=0, log_count=0)

    offset = _load_summary_offset(state_path)
    size = log_path.stat().st_size
    if offset > size:
        offset = 0

    with log_path.open("rb") as handle:
        handle.seek(offset)
        raw = handle.read()
        new_offset = handle.tell()

    text = raw.decode("utf-8-sig", errors="replace")
    lines = [
        line
        for line in text.splitlines()
        if line.strip() and "[SUMMARY]" not in line
    ]
    if not lines:
        return SummarySource(text="", offset=new_offset, log_count=0)

    joined = "\n".join(lines)
    if len(joined) > max_chars:
        joined = joined[-max_chars:]
    return SummarySource(text=joined, offset=new_offset, log_count=len(lines))


def build_summary_prompt(logs: str, *, trigger: str) -> str:
    """Build the prompt sent to the summary LLM."""

    return PROMPT_TEMPLATE.format(trigger=trigger, logs=logs)


@dataclass(slots=True, frozen=True)
class ParsedSummary:
    message: str
    next: str


def parse_summary_output(raw: str) -> ParsedSummary | None:
    """Parse model output into summary fields, or None when skipped/invalid."""

    text = raw.strip()
    if not text:
        return None
    if text.startswith("```"):
        text = _strip_code_fence(text)

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise SummaryGenerationError("Summary model returned invalid JSON.") from exc

    if not isinstance(parsed, dict):
        raise SummaryGenerationError("Summary model returned a non-object JSON value.")

    message = str(parsed.get("message") or "").strip()
    next_action = str(parsed.get("next") or "").strip()
    if not message:
        return None
    return ParsedSummary(message=message, next=next_action)


def _generate_with_retry(client: SummaryClient, prompt: str) -> str:
    attempts = 2
    for attempt in range(attempts):
        try:
            return client.generate_summary(prompt)
        except Exception as exc:
            if attempt == attempts - 1:
                get_logger(LogKind.Debug).warning(
                    "Summary generation failed",
                    extra={"error_type": type(exc).__name__, "reason": str(exc)},
                )
                raise SummaryGenerationError("Summary generation failed.") from exc
    return ""


def _load_summary_offset(path: Path) -> int:
    if not path.exists():
        return 0
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return 0
    if not isinstance(raw, dict):
        return 0
    try:
        return int(raw.get("offset", 0))
    except (TypeError, ValueError):
        return 0


def _save_summary_state(path: Path, offset: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"offset": offset}, ensure_ascii=True, sort_keys=True),
        encoding="utf-8",
    )


def _strip_code_fence(text: str) -> str:
    lines = text.splitlines()
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].startswith("```"):
        lines = lines[:-1]
    return "\n".join(lines).strip()
