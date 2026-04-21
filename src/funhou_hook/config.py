"""Configuration loading for Phase 1 hard-rule classification."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .messages import Level

PACKAGE_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_PATH = PACKAGE_ROOT / "config" / "funhou.toml"
DEFAULT_LOG_PATH = Path("/tmp/funhou.log")
DEFAULT_LEVELS = ("info", "warning", "danger", "error")
DEFAULT_MENTION_LEVELS = ("warning", "danger")


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


@dataclass(slots=True, frozen=True)
class SlackChannelConfig:
    """Dispatcher settings for the Slack output channel."""

    enabled: bool = False
    webhook: str | None = None
    levels: tuple[Level, ...] = DEFAULT_LEVELS
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


def _coerce_levels(values: list[str] | tuple[str, ...]) -> tuple[Level, ...]:
    return tuple(_coerce_level(value) for value in values)


def _coerce_optional_string(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _load_channel(data: dict[str, Any]) -> TerminalChannelConfig:
    output = Path(data.get("output", DEFAULT_LOG_PATH))
    raw_levels = data.get("levels", list(DEFAULT_LEVELS))
    levels = _coerce_levels(raw_levels)
    return TerminalChannelConfig(output=output, levels=levels)


def _load_slack_channel(data: dict[str, Any]) -> SlackChannelConfig:
    enabled = bool(data.get("enabled", False))
    webhook = _coerce_optional_string(data.get("webhook"))
    raw_levels = data.get("levels", list(DEFAULT_LEVELS))
    raw_mention_levels = data.get("mention_on", list(DEFAULT_MENTION_LEVELS))
    mention_to = _coerce_optional_string(data.get("mention_to"))

    levels = _coerce_levels(raw_levels)
    mention_on = _coerce_levels(raw_mention_levels)

    if enabled and webhook is None:
        raise ValueError("Slack webhook is required when channels.slack.enabled is true.")

    return SlackChannelConfig(
        enabled=enabled,
        webhook=webhook,
        levels=levels,
        mention_on=mention_on,
        mention_to=mention_to,
    )


def load_config(path: Path | None = None) -> FunhouConfig:
    """Load the funhou configuration from TOML."""

    config_path = path or DEFAULT_CONFIG_PATH
    raw = tomllib.loads(config_path.read_text(encoding="utf-8"))

    raw_rules = raw.get("rules", [])
    rules = tuple(
        HardRule(match=item["match"], level=_coerce_level(item["level"])) for item in raw_rules
    )

    channels = raw.get("channels", {})
    terminal = _load_channel(channels.get("terminal", {}))
    slack = _load_slack_channel(channels.get("slack", {}))
    default_level = _coerce_level(raw.get("defaults", {}).get("level", "warning"))

    return FunhouConfig(
        rules=rules,
        terminal=terminal,
        slack=slack,
        default_level=default_level,
    )
