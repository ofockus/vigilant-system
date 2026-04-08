"""
Regime Gate — Composite environment score gating trade entries.

Combines VPIN toxicity, ghost wall count, liquidation risk, volume drift,
and funding divergence into a single 0-100 score. Trading is blocked
when score falls below threshold (default 55/100).

Auto-resets after configurable timeout to prevent permanent blocks.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from loguru import logger


@dataclass
class RegimeState:
    score: float = 100.0           # composite 0-100
    blocked: bool = False
    block_since: float = 0.0
    block_reason: str = ""
    components: dict[str, float] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.components is None:
            self.components = {}


class RegimeGate:
    """Composite regime gate controlling trade entry permission."""

    def __init__(
        self,
        threshold: float = 55.0,
        block_timeout_s: int = 600,
    ) -> None:
        self.threshold = threshold
        self.block_timeout_s = block_timeout_s
        self.state = RegimeState()
        self._ema_score: float = 80.0
        self._alpha: float = 0.1

    def update(
        self,
        vpin: float = 0.0,
        ghost_count: int = 0,
        liq_intensity: float = 0.0,
        spoof_score: float = 0.0,
        drift_detected: bool = False,
        drift_magnitude: float = 0.0,
        funding_divergence: float = 0.0,
        flow_intensity: float = 0.5,
    ) -> RegimeState:
        """Recompute regime score from all components."""

        # Each component contributes to a 0-100 score (higher = safer)
        # VPIN: 0=safe, 1=toxic → invert
        vpin_score = max(0, (1 - vpin) * 100)

        # Ghosts: 0=safe, 10+=dangerous
        ghost_score = max(0, 100 - ghost_count * 10)

        # Liquidation intensity: 0=safe, 1=cascading
        liq_score = max(0, (1 - liq_intensity) * 100)

        # Spoof: 0=safe, 1=heavy spoofing
        spoof_s = max(0, (1 - spoof_score) * 100)

        # Drift: no drift=100, strong drift=lower
        drift_s = 100 - drift_magnitude * 50 if drift_detected else 100

        # Funding divergence: small=safe, large=risky
        fund_s = max(0, 100 - funding_divergence * 10000)

        # Flow intensity: moderate is good, extreme is dangerous
        flow_s = 100 - abs(flow_intensity - 0.5) * 100

        components = {
            "vpin": vpin_score,
            "ghost": ghost_score,
            "liquidation": liq_score,
            "spoof": spoof_s,
            "drift": drift_s,
            "funding": fund_s,
            "flow": flow_s,
        }

        # Weighted composite
        weights = {
            "vpin": 0.25,
            "ghost": 0.15,
            "liquidation": 0.20,
            "spoof": 0.10,
            "drift": 0.10,
            "funding": 0.10,
            "flow": 0.10,
        }

        raw_score = sum(components[k] * weights[k] for k in weights)
        raw_score = max(0, min(100, raw_score))

        # EMA smoothing to avoid flicker
        self._ema_score += self._alpha * (raw_score - self._ema_score)
        score = self._ema_score

        now = time.time()

        # Check block status
        was_blocked = self.state.blocked

        if score < self.threshold:
            if not self.state.blocked:
                self.state.blocked = True
                self.state.block_since = now
                below = [k for k, v in components.items() if v < 60]
                self.state.block_reason = f"Score {score:.1f} < {self.threshold} ({', '.join(below)})"
                logger.warning("REGIME BLOCKED | {}", self.state.block_reason)
        else:
            if self.state.blocked:
                self.state.blocked = False
                self.state.block_reason = ""
                logger.info("REGIME UNBLOCKED | score={:.1f}", score)

        # Auto-reset after timeout
        if self.state.blocked and (now - self.state.block_since) > self.block_timeout_s:
            self.state.blocked = False
            self.state.block_reason = ""
            logger.info("REGIME AUTO-RESET after {}s timeout", self.block_timeout_s)

        self.state.score = score
        self.state.components = components

        return self.state

    def is_ok(self) -> bool:
        return not self.state.blocked

    def get_status(self) -> dict[str, Any]:
        return {
            "score": self.state.score,
            "threshold": self.threshold,
            "blocked": self.state.blocked,
            "block_reason": self.state.block_reason,
            "components": self.state.components,
        }
