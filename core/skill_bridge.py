"""Adapters that connect OpenClaw-style orchestration with Binance market payloads."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict


@dataclass
class BinanceSkill:
    """Builds a normalized Binance payload that downstream skills can consume."""

    def market_context(self, market: Dict[str, Any]) -> Dict[str, Any]:
        symbol = str(market.get("primary_symbol", "")).replace(":", "").replace("/", "")
        return {
            "exchange": "binance",
            "symbol": symbol,
            "path": market.get("path", ""),
            "net_pct": float(market.get("net_pct", 0.0) or 0.0),
            "net_usd": float(market.get("net_usd", 0.0) or 0.0),
            "quote_volume_total": float(market.get("quote_volume_total", 0.0) or 0.0),
            "market_active": bool(market.get("market_active", True)),
            "market_spot": bool(market.get("market_spot", True)),
        }


@dataclass
class OpenClawSkill:
    """Transforms fusion outputs into a deterministic OpenClaw action plan."""

    score_threshold: float = 65.0

    def action_plan(self, confluence: Dict[str, Any], decision: Dict[str, Any]) -> Dict[str, Any]:
        score = float(confluence.get("score", 0.0) or 0.0)
        allowed = bool(decision.get("allow", False))

        if allowed and score >= self.score_threshold:
            action = "execute"
            reason = "decision_allow_and_score_ok"
        elif allowed:
            action = "watch"
            reason = "decision_allow_but_low_score"
        else:
            action = "block"
            reason = "fusion_veto"

        return {
            "engine": "openclaw",
            "action": action,
            "reason": reason,
            "score": score,
            "warnings": list(decision.get("warnings", [])),
            "vetoes": list(decision.get("vetoes", [])),
        }


class OpenClawBinanceBridge:
    """Produces a single payload where OpenClaw and Binance skills interoperate."""

    def __init__(self, score_threshold: float = 65.0) -> None:
        self._binance = BinanceSkill()
        self._openclaw = OpenClawSkill(score_threshold=score_threshold)

    def build_handoff(
        self,
        market: Dict[str, Any],
        confluence: Dict[str, Any],
        decision: Dict[str, Any],
    ) -> Dict[str, Any]:
        return {
            "binance": self._binance.market_context(market),
            "openclaw": self._openclaw.action_plan(confluence, decision),
        }
