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


def test_main_fans_out_messages_to_terminal_and_slack(
    runtime_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config_path = runtime_dir / "funhou.toml"
    terminal_log_path = runtime_dir / "funhou.log"
    operational_log_path = runtime_dir / "operational.log"
    delivered: list[tuple[str, str]] = []

    config_path.write_text(
        f"""
[channels.terminal]
output = "{terminal_log_path.as_posix()}"
levels = ["info", "warning", "danger", "error"]
message_types = ["log", "summary", "approval"]

[channels.slack]
enabled = true
levels = ["info", "warning", "danger", "error"]
message_types = ["log", "summary", "approval"]
""".strip(),
        encoding="utf-8",
    )
    payload = {
        "hook_event_name": "PreToolUse",
        "tool_name": "Read",
        "tool_input": {"file_path": "src/config.ts"},
        "session_id": "demo-session",
    }

    monkeypatch.setattr(sys, "argv", ["hook", str(config_path)])
    monkeypatch.setattr("funhou_hook.hook._read_stdin_bytes", lambda: json.dumps(payload).encode())
    monkeypatch.setattr(
        "funhou_hook.hook.initialize_logging",
        lambda: initialize_logging(operational_log_path),
    )
    monkeypatch.setattr(
        "funhou_hook.config._load_env",
        lambda path: {"SLACK_WEBHOOK_URL": "https://hooks.slack.com/services/T000/B000/XXXX"},
    )
    monkeypatch.setattr(
        "funhou_hook.dispatcher.send_slack_message",
        lambda message, config: delivered.append((message.type, getattr(message, "message", ""))),
    )

    result = main()

    assert result == 0
    assert "Read src/config.ts" in terminal_log_path.read_text(encoding="utf-8-sig")
    assert delivered == [("log", "Read src/config.ts")]

    response = json.loads(capsys.readouterr().out.strip())
    assert response == {
        "event": "PreToolUse",
        "level": "warning",
        "tool": "Read",
        "target": "src/config.ts",
    }


def test_main_continues_when_slack_delivery_fails(
    runtime_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config_path = runtime_dir / "funhou.toml"
    terminal_log_path = runtime_dir / "funhou.log"
    operational_log_path = runtime_dir / "operational.log"

    config_path.write_text(
        f"""
[channels.terminal]
output = "{terminal_log_path.as_posix()}"
levels = ["info", "warning", "danger", "error"]
message_types = ["log", "summary", "approval"]

[channels.slack]
enabled = true
levels = ["info", "warning", "danger", "error"]
message_types = ["log", "summary", "approval"]
""".strip(),
        encoding="utf-8",
    )
    payload = {
        "hook_event_name": "PreToolUse",
        "tool_name": "Read",
        "tool_input": {"file_path": "src/config.ts"},
        "session_id": "demo-session",
    }

    monkeypatch.setattr(sys, "argv", ["hook", str(config_path)])
    monkeypatch.setattr("funhou_hook.hook._read_stdin_bytes", lambda: json.dumps(payload).encode())
    monkeypatch.setattr(
        "funhou_hook.hook.initialize_logging",
        lambda: initialize_logging(operational_log_path),
    )
    monkeypatch.setattr(
        "funhou_hook.config._load_env",
        lambda path: {"SLACK_WEBHOOK_URL": "https://hooks.slack.com/services/T000/B000/XXXX"},
    )

    from funhou_hook.slack_sender import SlackDeliveryError

    def fail_send(message: object, config: object) -> None:
        raise SlackDeliveryError("Slack webhook returned HTTP 500.")

    monkeypatch.setattr("funhou_hook.dispatcher.send_slack_message", fail_send)

    result = main()

    assert result == 0
    assert "Read src/config.ts" in terminal_log_path.read_text(encoding="utf-8-sig")
    operational_log = operational_log_path.read_text(encoding="utf-8")
    assert "[ERROR] Slack delivery failed" in operational_log

    response = json.loads(capsys.readouterr().out.strip())
    assert response["event"] == "PreToolUse"
