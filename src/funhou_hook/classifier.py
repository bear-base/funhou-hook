"""Hard-rule based danger classification for Phase 1."""

from __future__ import annotations

from dataclasses import dataclass
from fnmatch import fnmatch

from .config import FunhouConfig, HardRule
from .messages import Level


@dataclass(slots=True, frozen=True)
class ToolEvent:
    """Normalized tool event extracted from hook stdin."""

    tool_name: str
    target: str
    payload: dict[str, object]

    @property
    def signature(self) -> str:
        return f"{self.tool_name}({self.target})"


def classify_event(event: ToolEvent, config: FunhouConfig) -> Level:
    """Return the first matching hard-rule level, or the configured default."""

    for rule in config.rules:
        if _matches(rule, event):
            return rule.level
    return config.default_level


def _matches(rule: HardRule, event: ToolEvent) -> bool:
    pattern = rule.match.strip()
    if "(" in pattern and pattern.endswith(")"):
        tool_pattern, raw_target_pattern = pattern[:-1].split("(", 1)
        if not _match_tool(tool_pattern, event.tool_name):
            return False
        return _match_alternatives(raw_target_pattern, event.target)

    return _match_alternatives(pattern, event.tool_name)


def _match_tool(pattern: str, tool_name: str) -> bool:
    return any(fnmatch(tool_name, option.strip()) for option in pattern.split("|"))


def _match_alternatives(pattern: str, value: str) -> bool:
    return any(fnmatch(value, option.strip()) for option in pattern.split("|"))
