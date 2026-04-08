"""
Append-only JSONL trade journal and JSON state persistence.

Every trade entry/exit is recorded as a single JSON line for post-analysis.
Calibration state is saved/loaded as a JSON file to survive restarts.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import orjson
from loguru import logger


class TradeJournal:
    """Append-only JSONL journal for trade records."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def record(self, entry: dict[str, Any]) -> None:
        with open(self.path, "ab") as f:
            f.write(orjson.dumps(entry) + b"\n")

    def read_last(self, n: int = 20) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        lines = self.path.read_text().strip().split("\n")
        recent = lines[-n:] if len(lines) >= n else lines
        result = []
        for line in recent:
            if line.strip():
                try:
                    result.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        return result


class StateStore:
    """JSON file for persisting calibration state across restarts."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def save(self, state: dict[str, Any]) -> None:
        with open(self.path, "wb") as f:
            f.write(orjson.dumps(state, option=orjson.OPT_INDENT_2))
        logger.debug("State saved to {}", self.path)

    def load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {}
        try:
            return json.loads(self.path.read_text())
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("Failed to load state: {}", e)
            return {}
