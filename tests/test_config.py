import shutil
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest

from funhou_hook.config import load_config


@pytest.fixture
def config_dir() -> Iterator[Path]:
    path = Path(__file__).resolve().parent / ".tmp" / uuid.uuid4().hex
    path.mkdir(parents=True, exist_ok=False)
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


@pytest.fixture(autouse=True)
def clear_slack_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SLACK_WEBHOOK_URL", raising=False)
    monkeypatch.delenv("SLACK_MENTION_TO", raising=False)


def test_load_config_reads_slack_values_from_env_loader(
    config_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = config_dir / "funhou.toml"
    monkeypatch.setattr(
        "funhou_hook.config._load_env",
        lambda path: {
            "SLACK_WEBHOOK_URL": "https://hooks.slack.com/services/T000/B000/XXXX",
            "SLACK_MENTION_TO": "@team",
        },
    )
    config_path.write_text(
        """
[[rules]]
match = "Read|Glob|Grep"
level = "info"

[defaults]
level = "warning"

[channels.terminal]
output = "/tmp/custom-funhou.log"
levels = ["info", "warning"]
message_types = ["log", "summary"]

[channels.slack]
enabled = true
levels = ["warning", "danger", "error"]
message_types = ["approval", "summary"]
mention_on = ["danger", "error"]
""".strip(),
        encoding="utf-8",
    )

    config = load_config(config_path)

    assert config.terminal.output == Path("/tmp/custom-funhou.log")
    assert config.terminal.levels == ("info", "warning")
    assert config.terminal.message_types == ("log", "summary")
    assert config.slack.enabled is True
    assert config.slack.webhook == "https://hooks.slack.com/services/T000/B000/XXXX"
    assert config.slack.levels == ("warning", "danger", "error")
    assert config.slack.message_types == ("approval", "summary")
    assert config.slack.mention_on == ("danger", "error")
    assert config.slack.mention_to == "@team"


def test_load_config_allows_disabled_slack_without_env_values(
    config_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = config_dir / "funhou.toml"
    monkeypatch.setattr("funhou_hook.config._load_env", lambda path: {})
    config_path.write_text(
        """
[channels.terminal]
output = "/tmp/funhou.log"

[channels.slack]
enabled = false
levels = ["info", "warning"]
mention_on = ["warning"]
""".strip(),
        encoding="utf-8",
    )

    config = load_config(config_path)

    assert config.slack.enabled is False
    assert config.slack.webhook is None
    assert config.slack.levels == ("info", "warning")
    assert config.terminal.message_types == ("log", "summary", "approval")
    assert config.slack.message_types == ("log", "summary", "approval")
    assert config.slack.mention_on == ("warning",)


def test_load_config_rejects_enabled_slack_without_env_webhook(
    config_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = config_dir / "funhou.toml"
    monkeypatch.setattr("funhou_hook.config._load_env", lambda path: {})
    config_path.write_text(
        """
[channels.terminal]
output = "/tmp/funhou.log"

[channels.slack]
enabled = true
""".strip(),
        encoding="utf-8",
    )

    with pytest.raises(
        ValueError,
        match="Slack webhook is required when channels.slack.enabled is true.",
    ):
        load_config(config_path)


def test_load_config_rejects_invalid_slack_level(
    config_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = config_dir / "funhou.toml"
    monkeypatch.setattr(
        "funhou_hook.config._load_env",
        lambda path: {"SLACK_WEBHOOK_URL": "https://hooks.slack.com/services/T000/B000/XXXX"},
    )
    config_path.write_text(
        """
[channels.terminal]
output = "/tmp/funhou.log"

[channels.slack]
enabled = true
levels = ["info", "noisy"]
""".strip(),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="Unsupported level: noisy"):
        load_config(config_path)


def test_load_config_rejects_invalid_terminal_message_type(
    config_dir: Path,
) -> None:
    config_path = config_dir / "funhou.toml"
    config_path.write_text(
        """
[channels.terminal]
output = "/tmp/funhou.log"
message_types = ["log", "digest"]
""".strip(),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="Unsupported message type: digest"):
        load_config(config_path)


def test_load_config_rejects_invalid_slack_message_type(
    config_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = config_dir / "funhou.toml"
    monkeypatch.setattr(
        "funhou_hook.config._load_env",
        lambda path: {"SLACK_WEBHOOK_URL": "https://hooks.slack.com/services/T000/B000/XXXX"},
    )
    config_path.write_text(
        """
[channels.terminal]
output = "/tmp/funhou.log"

[channels.slack]
enabled = true
message_types = ["approval", "status"]
""".strip(),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="Unsupported message type: status"):
        load_config(config_path)


def test_load_config_rejects_invalid_slack_mention_level(
    config_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = config_dir / "funhou.toml"
    monkeypatch.setattr(
        "funhou_hook.config._load_env",
        lambda path: {"SLACK_WEBHOOK_URL": "https://hooks.slack.com/services/T000/B000/XXXX"},
    )
    config_path.write_text(
        """
[channels.terminal]
output = "/tmp/funhou.log"

[channels.slack]
enabled = true
mention_on = ["warning", "urgent"]
""".strip(),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="Unsupported level: urgent"):
        load_config(config_path)


def test_load_env_reads_env_example() -> None:
    from funhou_hook.config import _load_env

    env = _load_env(Path(__file__).resolve().parents[1] / "config" / ".env.example")

    assert env["SLACK_WEBHOOK_URL"] == "https://hooks.slack.com/services/T000/B000/XXXX"
    assert env["SLACK_MENTION_TO"] == "@you"


def test_load_env_prefers_os_env_over_env_file(monkeypatch: pytest.MonkeyPatch) -> None:
    from funhou_hook.config import _load_env

    monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.slack.com/services/OVERRIDE")

    env = _load_env(Path(__file__).resolve().parents[1] / "config" / ".env.example")

    assert env["SLACK_WEBHOOK_URL"] == "https://hooks.slack.com/services/OVERRIDE"
