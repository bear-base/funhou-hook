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
    SummaryProviderResult,
    SummarySource,
    build_summary_message,
    read_summary_source,
)


class FakeSummaryProvider:
    def __init__(self, response: SummaryProviderResult | Exception) -> None:
        self.response = response
        self.calls: list[tuple[SummarySource, str]] = []

    def generate_summary(self, source: SummarySource, *, trigger: str) -> SummaryProviderResult:
        self.calls.append((source, trigger))
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


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
    provider = FakeSummaryProvider(
        SummaryProviderResult.generated(
            message="Build command was prepared.",
            next="Check the build result.",
        )
    )

    message = build_summary_message(
        trigger="Stop",
        terminal=_terminal(log_path),
        summary=_summary_config(state_path),
        provider=provider,
        now=datetime(2026, 4, 9, 10, 15, tzinfo=UTC),
    )

    assert isinstance(message, SummaryMessage)
    assert message.message == "Build command was prepared."
    assert message.next == "Check the build result."
    assert message.log_count == 1
    assert message.trigger == "Stop"
    assert provider.calls[0][1] == "Stop"
    assert "npm run build" in provider.calls[0][0].text
    assert json.loads(state_path.read_text(encoding="utf-8"))["offset"] == log_path.stat().st_size


def test_build_summary_message_skips_provider_skip_and_advances_offset(
    runtime_dir: Path,
) -> None:
    log_path = runtime_dir / "funhou.log"
    state_path = runtime_dir / "summary-state.json"
    log_path.write_text("10:02:00 [INFO] Read: Read src/config.py\n", encoding="utf-8")
    provider = FakeSummaryProvider(SummaryProviderResult.skipped(reason="not meaningful"))

    message = build_summary_message(
        trigger="Stop",
        terminal=_terminal(log_path),
        summary=_summary_config(state_path),
        provider=provider,
    )

    assert message is None
    assert json.loads(state_path.read_text(encoding="utf-8"))["offset"] == log_path.stat().st_size


def test_build_summary_message_keeps_offset_on_provider_failure(
    runtime_dir: Path,
) -> None:
    log_path = runtime_dir / "funhou.log"
    state_path = runtime_dir / "summary-state.json"
    log_path.write_text("10:02:00 [WARN] Bash: Bash npm run build\n", encoding="utf-8")
    provider = FakeSummaryProvider(SummaryProviderResult.failed(reason="timeout"))

    message = build_summary_message(
        trigger="Stop",
        terminal=_terminal(log_path),
        summary=_summary_config(state_path),
        provider=provider,
    )

    assert message is None
    assert not state_path.exists()


def test_build_summary_message_keeps_offset_on_provider_exception(runtime_dir: Path) -> None:
    log_path = runtime_dir / "funhou.log"
    state_path = runtime_dir / "summary-state.json"
    log_path.write_text("10:02:00 [WARN] Bash: Bash npm run build\n", encoding="utf-8")
    provider = FakeSummaryProvider(RuntimeError("timeout"))

    message = build_summary_message(
        trigger="Stop",
        terminal=_terminal(log_path),
        summary=_summary_config(state_path),
        provider=provider,
    )

    assert message is None
    assert not state_path.exists()
