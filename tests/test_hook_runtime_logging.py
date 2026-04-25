from __future__ import annotations

import json
import shutil
import sys
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest

from funhou_hook.hook import main
from funhou_hook.logging import LogKind, get_logger, initialize_logging


@pytest.fixture
def runtime_dir() -> Iterator[Path]:
    path = Path(__file__).resolve().parent / ".tmp" / uuid.uuid4().hex
    path.mkdir(parents=True, exist_ok=False)
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)
        for kind in LogKind:
            logger = get_logger(kind)
            handlers = list(logger.handlers)
            for handler in handlers:
                logger.removeHandler(handler)
                handler.close()


def test_runtime_error_uses_operational_details_and_notification_summary(
    runtime_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = runtime_dir / "funhou.toml"
    terminal_log_path = runtime_dir / "funhou.log"
    operational_log_path = runtime_dir / "operational.log"
    debug_log_path = runtime_dir / "funhou-debug.log"
    input_debug_log_path = runtime_dir / "funhou-input-debug.log"
    correlation_debug_log_path = runtime_dir / "funhou-correlation-debug.log"
    debug_log_path.write_text("existing debug\n", encoding="utf-8")
    input_debug_log_path.write_text("existing input\n", encoding="utf-8")
    debug_size = debug_log_path.stat().st_size
    input_debug_size = input_debug_log_path.stat().st_size

    config_path.write_text(
        f"""
[channels.terminal]
output = "{terminal_log_path.as_posix()}"
levels = ["info", "warning", "danger", "error"]
""".strip(),
        encoding="utf-8",
    )
    payload = {
        "hook_event_name": "PreToolUse",
        "tool_name": "Read",
        "tool_input": {"file_path": "C:\\secret\\settings.toml"},
        "session_id": "demo-session",
    }

    def raise_runtime_error(payload: dict[str, object], config: object) -> list[object]:
        raise ValueError("boom C:\\secret\\settings.toml API_KEY")

    monkeypatch.setattr(sys, "argv", ["hook", str(config_path)])
    monkeypatch.setattr("funhou_hook.hook._read_stdin_bytes", lambda: json.dumps(payload).encode())
    monkeypatch.setattr("funhou_hook.hook._build_messages", raise_runtime_error)
    monkeypatch.setattr(
        "funhou_hook.hook.initialize_logging",
        lambda: initialize_logging(operational_log_path),
    )
    monkeypatch.setattr("funhou_hook.hook.DEBUG_LOG_PATH", debug_log_path)
    monkeypatch.setattr("funhou_hook.hook.INPUT_DEBUG_LOG_PATH", input_debug_log_path)
    monkeypatch.setattr("funhou_hook.hook.CORRELATION_DEBUG_LOG_PATH", correlation_debug_log_path)

    with pytest.raises(ValueError, match="boom"):
        main()

    operational_log = operational_log_path.read_text(encoding="utf-8")
    assert "Hook received" in operational_log
    assert "Config loaded" in operational_log
    assert "Hook runtime error" in operational_log
    assert "event_type='PreToolUse'" in operational_log
    assert "ValueError" in operational_log
    assert "Traceback" in operational_log
    assert "API_KEY" in operational_log

    notification = terminal_log_path.read_text(encoding="utf-8-sig")
    assert "エラーが発生しました" in notification
    assert "ログを確認" in notification
    assert "Traceback" not in notification
    assert "ValueError" not in notification
    assert "C:\\secret\\settings.toml" not in notification
    assert "API_KEY" not in notification

    assert debug_log_path.stat().st_size == debug_size
    assert input_debug_log_path.stat().st_size == input_debug_size
    assert not correlation_debug_log_path.exists()
