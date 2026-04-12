"""Thin wrapper so Claude Code can call ``hook.py`` directly."""

from __future__ import annotations

import runpy
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


if __name__ == "__main__":
    runpy.run_module("funhou_hook.hook", run_name="__main__")
