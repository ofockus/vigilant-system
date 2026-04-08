"""
L4: Adversarial Shield — Jitter, ghost wall detection, spoof classification.

Protects against market manipulation by detecting:
- Ghost walls: large orders that appear and disappear quickly
- Spoofing: layered orders intended to mislead
- Adaptive jitter for timing randomization
"""

from __future__ import annotations

import random
import time
from collections import deque
from dataclasses import dataclass, field


@dataclass
class ShieldSignal:
    ghost_count: int = 0          # ghost walls detected in window
    spoof_score: float = 0.0      # 0 to 1 (1 = definite spoofing)
    safe: bool = True
    jitter_factor: float = 1.0    # timing randomization multiplier


@dataclass
class OrderSnapshot:
    timestamp: float
    price: float
    size: float
    side: str  # "bid" or "ask"


class GhostWallTracker:
    """Tracks order book levels that appear and vanish quickly (ghost walls)."""

    def __init__(self, ttl_s: float = 5.0, min_size_multiplier: float = 3.0) -> None:
        self.ttl_s = ttl_s
        self.min_size_mult = min_size_multiplier
        self.prev_levels: dict[str, dict[float, float]] = {"bid": {}, "ask": {}}
        self.ghost_events: deque[float] = deque(maxlen=200)  # timestamps
        self.avg_size: float = 0.0
        self.size_count: int = 0

    def update(self, bids: list[list[float]], asks: list[list[float]], now: float) -> int:
        """Compare current book with previous snapshot. Return ghost count in window."""
        current_bid = {price: size for price, size in bids[:20]}
        current_ask = {price: size for price, size in asks[:20]}

        # Update running average order size
        all_sizes = [s for _, s in bids[:20]] + [s for _, s in asks[:20]]
        if all_sizes:
            batch_avg = sum(all_sizes) / len(all_sizes)
            self.size_count += 1
            self.avg_size += (batch_avg - self.avg_size) / self.size_count

        threshold = self.avg_size * self.min_size_mult

        # Check for vanished large orders (ghost walls)
        for side, prev, curr in [
            ("bid", self.prev_levels["bid"], current_bid),
            ("ask", self.prev_levels["ask"], current_ask),
        ]:
            for price, size in prev.items():
                if size >= threshold and price not in curr:
                    self.ghost_events.append(now)

        self.prev_levels = {"bid": current_bid, "ask": current_ask}

        # Count ghosts in recent window
        cutoff = now - 60.0
        while self.ghost_events and self.ghost_events[0] < cutoff:
            self.ghost_events.popleft()

        return len(self.ghost_events)


class SpoofClassifier:
    """Detects spoofing patterns: layered orders with size imbalance."""

    def classify(self, bids: list[list[float]], asks: list[list[float]]) -> float:
        """Return spoof probability [0, 1]."""
        if not bids or not asks:
            return 0.0

        # Check for layered patterns: many similar-sized orders at consecutive levels
        bid_sizes = [s for _, s in bids[:10]]
        ask_sizes = [s for _, s in asks[:10]]

        if len(bid_sizes) < 3 or len(ask_sizes) < 3:
            return 0.0

        # Size uniformity (spoofs tend to be same-sized)
        bid_cv = _cv(bid_sizes)
        ask_cv = _cv(ask_sizes)

        # Imbalance ratio
        total_bid = sum(bid_sizes)
        total_ask = sum(ask_sizes)
        imbalance = abs(total_bid - total_ask) / (total_bid + total_ask + 1e-15)

        # Low CV + high imbalance = likely spoofing
        uniformity = max(1.0 - min(bid_cv, ask_cv), 0.0)
        score = uniformity * 0.5 + imbalance * 0.5

        return min(score, 1.0)


def _cv(values: list[float]) -> float:
    """Coefficient of variation."""
    if not values:
        return 1.0
    mean = sum(values) / len(values)
    if mean < 1e-15:
        return 1.0
    variance = sum((v - mean) ** 2 for v in values) / len(values)
    return (variance ** 0.5) / mean


class AdversarialShield:
    """L4 signal layer: ghost walls + spoofing + jitter."""

    def __init__(self) -> None:
        self.ghost_tracker = GhostWallTracker()
        self.spoof_classifier = SpoofClassifier()
        self._jitter_base = 0.8

    def update(self, bids: list[list[float]], asks: list[list[float]], now: float) -> ShieldSignal:
        ghost_count = self.ghost_tracker.update(bids, asks, now)
        spoof_score = self.spoof_classifier.classify(bids, asks)

        # Adaptive jitter: increase randomization when manipulation detected
        manipulation_level = min((ghost_count / 10) * 0.5 + spoof_score * 0.5, 1.0)
        jitter = self._jitter_base + random.uniform(0, 0.4) * (1 + manipulation_level)

        safe = ghost_count < 8 and spoof_score < 0.6

        return ShieldSignal(
            ghost_count=ghost_count,
            spoof_score=spoof_score,
            safe=safe,
            jitter_factor=jitter,
        )
