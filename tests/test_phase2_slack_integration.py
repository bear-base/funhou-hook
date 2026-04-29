from __future__ import annotations

import json
import shutil
import sys
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest

from funhou_hook.config import SlackChannelConfig, TerminalChannelConfig, load_config
from funhou_hook.dispatcher import dispatch_message
from funhou_hook.hook import main
from funhou_hook.logging import LogKind, get_logger, initialize_logging
from funhou_hook.messages import ApprovalMessage, SummaryMessage
from funhou_hook.slack_sender import SlackDeliveryError


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


@pytest.fixture(autouse=True)
def clear_slack_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SLACK_WEBHOOK_URL", raising=False)
    monkeypatch.delenv("SLACK_MENTION_TO", raising=False)


def _write_config(
    path: Path,
    terminal_log_path: Path,
    *,
    slack_enabled: bool,
    slack_levels: tuple[str, ...] = ("info", "warning", "danger", "error"),
    slack_message_types: tuple[str, ...] = ("log", "summary", "approval"),
) -> None:
    path.write_text(
        f"""
[[rules]]
match = "Read|Glob|Grep"
level = "info"

[[rules]]
match = "Bash(*deploy*|*migrate*)"
level = "danger"

[defaults]
level = "warning"

[channels.terminal]
output = "{terminal_log_path.as_posix()}"
levels = ["info", "warning", "danger", "error"]
message_types = ["log", "summary", "approval"]

[channels.slack]
enabled = {str(slack_enabled).lower()}
levels = [{_toml_strings(slack_levels)}]
message_types = [{_toml_strings(slack_message_types)}]
mention_on = ["warning", "danger"]
""".strip(),
        encoding="utf-8",
    )


def _toml_strings(values: tuple[str, ...]) -> str:
    return ", ".join(f'"{value}"' for value in values)


def _pre_tool_payload(
    *,
    tool_name: str = "Read",
    tool_input: dict[str, str] | None = None,
) -> dict[str, object]:
    return {
        "hook_event_name": "PreToolUse",
        "tool_name": tool_name,
        "tool_input": tool_input or {"file_path": "src/config.py"},
        "session_id": "phase2-slack-session",
    }


def test_phase2_slack_disabled_keeps_terminal_only(
    runtime_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config_path = runtime_dir / "funhou.toml"
    terminal_log_path = runtime_dir / "funhou.log"
    operational_log_path = runtime_dir / "operational.log"
    delivered: list[str] = []
    _write_config(config_path, terminal_log_path, slack_enabled=False)

    monkeypatch.setattr(sys, "argv", ["hook", str(config_path)])
    monkeypatch.setattr(
        "funhou_hook.hook._read_stdin_bytes",
        lambda: json.dumps(_pre_tool_payload()).encode(),
    )
    monkeypatch.setattr(
        "funhou_hook.hook.initialize_logging",
        lambda: initialize_logging(operational_log_path),
    )
    monkeypatch.setattr(
        "funhou_hook.dispatcher.send_slack_message",
        lambda message, config: delivered.append(message.type),
    )

    result = main()

    assert result == 0
    assert "Read src/config.py" in terminal_log_path.read_text(encoding="utf-8-sig")
    assert delivered == []
    response = json.loads(capsys.readouterr().out.strip())
    assert response["event"] == "PreToolUse"
    assert response["level"] == "info"


def test_phase2_hook_fans_out_to_slack_with_env_webhook_and_mention(
    runtime_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config_path = runtime_dir / "funhou.toml"
    terminal_log_path = runtime_dir / "funhou.log"
    operational_log_path = runtime_dir / "operational.log"
    delivered: list[tuple[str, str | None, tuple[str, ...]]] = []
    _write_config(config_path, terminal_log_path, slack_enabled=True)

    monkeypatch.setattr(sys, "argv", ["hook", str(config_path)])
    monkeypatch.setattr(
        "funhou_hook.hook._read_stdin_bytes",
        lambda: json.dumps(
            _pre_tool_payload(tool_name="Bash", tool_input={"command": "npm run build"})
        ).encode(),
    )
    monkeypatch.setattr(
        "funhou_hook.hook.initialize_logging",
        lambda: initialize_logging(operational_log_path),
    )
    monkeypatch.setattr(
        "funhou_hook.config._load_env",
        lambda path: {
            "SLACK_WEBHOOK_URL": "https://hooks.slack.com/services/T000/B000/XXXX",
            "SLACK_MENTION_TO": "<@U01234567>",
        },
    )
    monkeypatch.setattr(
        "funhou_hook.dispatcher.send_slack_message",
        lambda message, config: delivered.append(
            (message.type, config.mention_to, config.mention_on)
        ),
    )

    result = main()

    assert result == 0
    assert "Bash npm run build" in terminal_log_path.read_text(encoding="utf-8-sig")
    assert delivered == [("log", "<@U01234567>", ("warning", "danger"))]
    response = json.loads(capsys.readouterr().out.strip())
    assert response["level"] == "warning"


def test_phase2_enabled_slack_requires_env_webhook(
    runtime_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = runtime_dir / "funhou.toml"
    terminal_log_path = runtime_dir / "funhou.log"
    _write_config(config_path, terminal_log_path, slack_enabled=True)
    monkeypatch.setattr("funhou_hook.config._load_env", lambda path: {})

    with pytest.raises(
        ValueError,
        match="Slack webhook is required when channels.slack.enabled is true.",
    ):
        load_config(config_path)


def test_phase2_slack_level_filter_blocks_lower_level_messages(
    runtime_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = runtime_dir / "funhou.toml"
    terminal_log_path = runtime_dir / "funhou.log"
    operational_log_path = runtime_dir / "operational.log"
    delivered: list[str] = []
    _write_config(
        config_path,
        terminal_log_path,
        slack_enabled=True,
        slack_levels=("danger",),
    )

    monkeypatch.setattr(sys, "argv", ["hook", str(config_path)])
    monkeypatch.setattr(
        "funhou_hook.hook._read_stdin_bytes",
        lambda: json.dumps(_pre_tool_payload()).encode(),
    )
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
        lambda message, config: delivered.append(message.type),
    )

    result = main()

    assert result == 0
    assert "Read src/config.py" in terminal_log_path.read_text(encoding="utf-8-sig")
    assert delivered == []


def test_phase2_slack_message_type_filter_blocks_logs(
    runtime_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = runtime_dir / "funhou.toml"
    terminal_log_path = runtime_dir / "funhou.log"
    operational_log_path = runtime_dir / "operational.log"
    delivered: list[str] = []
    _write_config(
        config_path,
        terminal_log_path,
        slack_enabled=True,
        slack_message_types=("approval", "summary"),
    )

    monkeypatch.setattr(sys, "argv", ["hook", str(config_path)])
    monkeypatch.setattr(
        "funhou_hook.hook._read_stdin_bytes",
        lambda: json.dumps(_pre_tool_payload()).encode(),
    )
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
        lambda message, config: delivered.append(message.type),
    )

    result = main()

    assert result == 0
    assert "Read src/config.py" in terminal_log_path.read_text(encoding="utf-8-sig")
    assert delivered == []


def test_phase2_slack_failure_is_recorded_without_losing_terminal_output(
    runtime_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = runtime_dir / "funhou.toml"
    terminal_log_path = runtime_dir / "funhou.log"
    operational_log_path = runtime_dir / "operational.log"
    _write_config(config_path, terminal_log_path, slack_enabled=True)

    monkeypatch.setattr(sys, "argv", ["hook", str(config_path)])
    monkeypatch.setattr(
        "funhou_hook.hook._read_stdin_bytes",
        lambda: json.dumps(_pre_tool_payload()).encode(),
    )
    monkeypatch.setattr(
        "funhou_hook.hook.initialize_logging",
        lambda: initialize_logging(operational_log_path),
    )
    monkeypatch.setattr(
        "funhou_hook.config._load_env",
        lambda path: {"SLACK_WEBHOOK_URL": "https://hooks.slack.com/services/T000/B000/XXXX"},
    )

    def fail_send(message: object, config: object) -> None:
        raise SlackDeliveryError("Slack webhook returned HTTP 500.")

    monkeypatch.setattr("funhou_hook.dispatcher.send_slack_message", fail_send)

    result = main()

    assert result == 0
    assert "Read src/config.py" in terminal_log_path.read_text(encoding="utf-8-sig")
    operational_log = operational_log_path.read_text(encoding="utf-8")
    assert "[ERROR] Slack delivery failed" in operational_log
    assert "event_type='log'" in operational_log
    assert "HTTP 500" in operational_log


def test_phase2_approval_message_reaches_slack_with_mention_settings(
    runtime_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    terminal_log_path = runtime_dir / "funhou.log"
    delivered: list[tuple[str, str | None, tuple[str, ...]]] = []
    terminal = TerminalChannelConfig(
        output=terminal_log_path,
        levels=("info", "warning", "danger", "error"),
        message_types=("log", "summary", "approval"),
    )
    slack = SlackChannelConfig(
        enabled=True,
        webhook="https://hooks.slack.com/services/T000/B000/XXXX",
        levels=("danger",),
        message_types=("approval",),
        mention_on=("danger",),
        mention_to="<@U01234567>",
    )
    message = ApprovalMessage(
        timestamp=datetime(2026, 4, 9, 10, 16, tzinfo=UTC),
        level="danger",
        tool="Bash",
        command="npx prisma migrate deploy",
        reason="Production migration",
    )
    monkeypatch.setattr(
        "funhou_hook.dispatcher.send_slack_message",
        lambda message, config: delivered.append(
            (message.type, config.mention_to, config.mention_on)
        ),
    )

    dispatch_message(message, terminal, slack)

    assert "[APPROVAL]" in terminal_log_path.read_text(encoding="utf-8-sig")
    assert delivered == [("approval", "<@U01234567>", ("danger",))]


def test_phase2_summary_message_is_deliverable_but_generation_is_out_of_scope(
    runtime_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    terminal_log_path = runtime_dir / "funhou.log"
    delivered: list[str] = []
    terminal = TerminalChannelConfig(
        output=terminal_log_path,
        levels=(),
        message_types=("summary",),
    )
    slack = SlackChannelConfig(
        enabled=True,
        webhook="https://hooks.slack.com/services/T000/B000/XXXX",
        levels=(),
        message_types=("summary",),
    )
    message = SummaryMessage(
        timestamp=datetime(2026, 4, 9, 10, 15, tzinfo=UTC),
        message="Config updated and tests passed.",
        next="Summary engine integration is a later task.",
        log_count=12,
        duration_sec=720,
    )
    monkeypatch.setattr(
        "funhou_hook.dispatcher.send_slack_message",
        lambda message, config: delivered.append(message.type),
    )

    dispatch_message(message, terminal, slack)

    contents = terminal_log_path.read_text(encoding="utf-8-sig")
    assert "[SUMMARY]" in contents
    assert "Config updated and tests passed." in contents
    assert delivered == ["summary"]
