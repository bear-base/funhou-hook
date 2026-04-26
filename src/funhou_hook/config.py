"""Configuration loading for Phase 1 hard-rule classification."""

from __future__ import annotations

import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from os import environ
from pathlib import Path
from typing import Any

try:
    from dotenv import dotenv_values
except ModuleNotFoundError:
    dotenv_values = None

from .messages import Level, MessageType

PACKAGE_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_PATH = PACKAGE_ROOT / "config" / "funhou.toml"
DEFAULT_ENV_PATH = PACKAGE_ROOT / "config" / ".env"
DEFAULT_LOG_PATH = Path("/tmp/funhou.log")
DEFAULT_LEVELS = ("info", "warning", "danger", "error")
DEFAULT_MENTION_LEVELS = ("warning", "danger")
DEFAULT_MESSAGE_TYPES = ("log", "summary", "approval")
SLACK_WEBHOOK_ENV = "SLACK_WEBHOOK_URL"
SLACK_MENTION_TO_ENV = "SLACK_MENTION_TO"


@dataclass(slots=True, frozen=True)
class HardRule:
    """A single hard rule from the configuration file."""

    match: str
    level: Level


@dataclass(slots=True, frozen=True)
class TerminalChannelConfig:
    """Dispatcher settings for the terminal output channel."""

    output: Path
    levels: tuple[Level, ...]
    message_types: tuple[MessageType, ...] = DEFAULT_MESSAGE_TYPES


@dataclass(slots=True, frozen=True)
class SlackChannelConfig:
    """Dispatcher settings for the Slack output channel."""

    enabled: bool = False
    webhook: str | None = None
    levels: tuple[Level, ...] = DEFAULT_LEVELS
    message_types: tuple[MessageType, ...] = DEFAULT_MESSAGE_TYPES
    mention_on: tuple[Level, ...] = DEFAULT_MENTION_LEVELS
    mention_to: str | None = None


ChannelConfig = TerminalChannelConfig


@dataclass(slots=True, frozen=True)
class FunhouConfig:
    """Configuration derived from the TOML file."""

    rules: tuple[HardRule, ...]
    terminal: TerminalChannelConfig
    slack: SlackChannelConfig = SlackChannelConfig()
    default_level: Level = "warning"


def _coerce_level(value: str) -> Level:
    if value not in set(DEFAULT_LEVELS):
        raise ValueError(f"Unsupported level: {value}")
    return value


def _coerce_message_type(value: str) -> MessageType:
    if value not in set(DEFAULT_MESSAGE_TYPES):
        raise ValueError(f"Unsupported message type: {value}")
    return value


def _coerce_levels(values: list[str] | tuple[str, ...]) -> tuple[Level, ...]:
    return tuple(_coerce_level(value) for value in values)


def _coerce_message_types(values: list[str] | tuple[str, ...]) -> tuple[MessageType, ...]:
    return tuple(_coerce_message_type(value) for value in values)


def _coerce_optional_string(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _load_channel(data: dict[str, Any]) -> TerminalChannelConfig:
    output = Path(data.get("output", DEFAULT_LOG_PATH))
    raw_levels = data.get("levels", list(DEFAULT_LEVELS))
    raw_message_types = data.get("message_types", list(DEFAULT_MESSAGE_TYPES))
    levels = _coerce_levels(raw_levels)
    message_types = _coerce_message_types(raw_message_types)
    return TerminalChannelConfig(output=output, levels=levels, message_types=message_types)


def _load_slack_channel(data: dict[str, Any], env: Mapping[str, str]) -> SlackChannelConfig:
    enabled = bool(data.get("enabled", False))
    webhook = _coerce_optional_string(env.get(SLACK_WEBHOOK_ENV))
    raw_levels = data.get("levels", list(DEFAULT_LEVELS))
    raw_message_types = data.get("message_types", list(DEFAULT_MESSAGE_TYPES))
    raw_mention_levels = data.get("mention_on", list(DEFAULT_MENTION_LEVELS))
    mention_to = _coerce_optional_string(env.get(SLACK_MENTION_TO_ENV))

    levels = _coerce_levels(raw_levels)
    message_types = _coerce_message_types(raw_message_types)
    mention_on = _coerce_levels(raw_mention_levels)

    if enabled and webhook is None:
        raise ValueError("Slack webhook is required when channels.slack.enabled is true.")

    return SlackChannelConfig(
        enabled=enabled,
        webhook=webhook,
        levels=levels,
        message_types=message_types,
        mention_on=mention_on,
        mention_to=mention_to,
    )


def load_config(path: Path | None = None) -> FunhouConfig:
    """Load the funhou configuration from TOML."""

    config_path = path or DEFAULT_CONFIG_PATH
    raw = tomllib.loads(config_path.read_text(encoding="utf-8"))
    env = _load_env(config_path.with_name(".env"))

    raw_rules = raw.get("rules", [])
    rules = tuple(
        HardRule(match=item["match"], level=_coerce_level(item["level"])) for item in raw_rules
    )

    channels = raw.get("channels", {})
    terminal = _load_channel(channels.get("terminal", {}))
    slack = _load_slack_channel(channels.get("slack", {}), env)
    default_level = _coerce_level(raw.get("defaults", {}).get("level", "warning"))

    return FunhouConfig(
        rules=rules,
        terminal=terminal,
        slack=slack,
        default_level=default_level,
    )


def _load_env(path: Path = DEFAULT_ENV_PATH) -> dict[str, str]:
    if dotenv_values is None:
        file_values = _read_env_fallback(path)
        return {**file_values, **environ}

    file_values = {key: value for key, value in dotenv_values(path).items() if value is not None}
    return {**file_values, **environ}


def _read_env_fallback(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}

    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        values[key.strip()] = value.strip().strip("\"'")
    return values
