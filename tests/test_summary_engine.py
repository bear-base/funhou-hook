from __future__ import annotations

import json
import shutil
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest

from funhou_hook.config import SummaryEngineConfig, TerminalChannelConfig
from funhou_hook.messages import SummaryMessage
from funhou_hook.summary_engine import (
    SummaryGenerationError,
    build_summary_message,
    build_summary_prompt,
    parse_summary_output,
    read_summary_source,
)


class FakeSummaryClient:
    def __init__(self, *responses: str | Exception) -> None:
        self.responses = list(responses)
        self.prompts: list[str] = []

    def generate_summary(self, prompt: str) -> str:
        self.prompts.append(prompt)
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


@pytest.fixture
def runtime_dir() -> Iterator[Path]:
    path = Path(__file__).resolve().parent / ".tmp" / uuid.uuid4().hex
    path.mkdir(parents=True, exist_ok=False)
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


def _terminal(path: Path) -> TerminalChannelConfig:
    return TerminalChannelConfig(
        output=path,
        levels=("info", "warning", "danger", "error"),
        message_types=("log", "summary", "approval"),
    )


def _summary_config(state_path: Path) -> SummaryEngineConfig:
    return SummaryEngineConfig(
        enabled=True,
        state_path=state_path,
        max_log_chars=8000,
    )


def test_read_summary_source_uses_offset_and_ignores_summary_lines(runtime_dir: Path) -> None:
    log_path = runtime_dir / "funhou.log"
    state_path = runtime_dir / "summary-state.json"
    old_line = "10:00:00 [INFO] Read: Read old.py\n"
    log_path.write_text(
        old_line
        + "10:01:00 [SUMMARY] old summary | next=continue\n"
        + "10:02:00 [WARN] Bash: Bash npm run build\n",
        encoding="utf-8",
    )
    state_path.write_text(json.dumps({"offset": len(old_line.encode())}), encoding="utf-8")

    source = read_summary_source(log_path, state_path, max_chars=8000)

    assert source.log_count == 1
    assert "old summary" not in source.text
    assert "npm run build" in source.text
    assert source.offset == log_path.stat().st_size


def test_build_summary_message_returns_message_and_updates_offset(runtime_dir: Path) -> None:
    log_path = runtime_dir / "funhou.log"
    state_path = runtime_dir / "summary-state.json"
    log_path.write_text("10:02:00 [WARN] Bash: Bash npm run build\n", encoding="utf-8")
    client = FakeSummaryClient(
        '{"message":"Build command was prepared.","next":"Check the build result."}'
    )

    message = build_summary_message(
        trigger="Stop",
        terminal=_terminal(log_path),
        summary=_summary_config(state_path),
        client=client,
        now=datetime(2026, 4, 9, 10, 15, tzinfo=UTC),
    )

    assert isinstance(message, SummaryMessage)
    assert message.message == "Build command was prepared."
    assert message.next == "Check the build result."
    assert message.log_count == 1
    assert message.trigger == "Stop"
    assert "発火元イベント: Stop" in client.prompts[0]
    assert json.loads(state_path.read_text(encoding="utf-8"))["offset"] == log_path.stat().st_size


def test_build_summary_message_skips_empty_model_output_and_advances_offset(
    runtime_dir: Path,
) -> None:
    log_path = runtime_dir / "funhou.log"
    state_path = runtime_dir / "summary-state.json"
    log_path.write_text("10:02:00 [INFO] Read: Read src/config.py\n", encoding="utf-8")
    client = FakeSummaryClient("")

    message = build_summary_message(
        trigger="Stop",
        terminal=_terminal(log_path),
        summary=_summary_config(state_path),
        client=client,
    )

    assert message is None
    assert json.loads(state_path.read_text(encoding="utf-8"))["offset"] == log_path.stat().st_size


def test_build_summary_message_retries_once_and_keeps_offset_on_failure(
    runtime_dir: Path,
) -> None:
    log_path = runtime_dir / "funhou.log"
    state_path = runtime_dir / "summary-state.json"
    log_path.write_text("10:02:00 [WARN] Bash: Bash npm run build\n", encoding="utf-8")
    client = FakeSummaryClient(RuntimeError("timeout"), RuntimeError("timeout"))

    message = build_summary_message(
        trigger="Stop",
        terminal=_terminal(log_path),
        summary=_summary_config(state_path),
        client=client,
    )

    assert message is None
    assert len(client.prompts) == 2
    assert not state_path.exists()


def test_parse_summary_output_rejects_invalid_json() -> None:
    with pytest.raises(SummaryGenerationError):
        parse_summary_output("not-json")


def test_build_summary_prompt_contains_logs_and_trigger() -> None:
    prompt = build_summary_prompt("10:00 [INFO] Read: Read src/config.py", trigger="Stop")

    assert "発火元イベント: Stop" in prompt
    assert "Read src/config.py" in prompt
