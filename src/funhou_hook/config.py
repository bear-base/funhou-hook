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


@dataclass(slots=True, frozen=True)
class HardRule:
    """A single hard rule from the configuration file."""

    match: str
    level: Level


@dataclass(slots=True, frozen=True)
class ChannelConfig:
    """Dispatcher settings for a single output channel."""

    output: Path
    levels: tuple[Level, ...]


@dataclass(slots=True, frozen=True)
class FunhouConfig:
    """Phase 1 configuration derived from the TOML file."""

    rules: tuple[HardRule, ...]
    terminal: ChannelConfig
    default_level: Level = "warning"


def _coerce_level(value: str) -> Level:
    if value not in set(DEFAULT_LEVELS):
        raise ValueError(f"Unsupported level: {value}")
    return value


def _load_channel(data: dict[str, Any]) -> ChannelConfig:
    output = Path(data.get("output", DEFAULT_LOG_PATH))
    raw_levels = data.get("levels", list(DEFAULT_LEVELS))
    levels = tuple(_coerce_level(item) for item in raw_levels)
    return ChannelConfig(output=output, levels=levels)


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
    default_level = _coerce_level(raw.get("defaults", {}).get("level", "warning"))

    return FunhouConfig(rules=rules, terminal=terminal, default_level=default_level)
