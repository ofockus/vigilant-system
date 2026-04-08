"""
L9: Whale Classifier.

Detects large trades (>10x average) and classifies them as:
- Momentum follow: genuine large buyer/seller → follow direction
- Spoof fade: manipulation → fade the apparent direction
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass

import numpy as np


@dataclass
class WhaleEvent:
    timestamp: float
    price: float
    volume: float
    is_buy: bool
    classification: str  # "momentum" or "spoof_fade"
    confidence: float    # 0 to 1


@dataclass
class WhaleSignal:
    whale_detected: bool = False
    latest_event: WhaleEvent | None = None
    recent_count: int = 0          # whales in last 5 min
    net_direction: float = 0.0     # -1 to +1 from recent whales
    total_whale_volume: float = 0.0


class WhaleClassifier:
    """L9 signal layer: detect and classify whale trades."""

    def __init__(self, multiplier: float = 10.0, window_s: float = 300.0) -> None:
        self.multiplier = multiplier
        self.window_s = window_s
        self.trade_sizes: deque[float] = deque(maxlen=2000)
        self.whale_events: deque[WhaleEvent] = deque(maxlen=100)

    def update(self, price: float, volume: float, is_buy: bool, timestamp: float,
               ghost_count: int = 0, spoof_score: float = 0.0) -> WhaleSignal:
        """Process a trade. Returns signal if whale detected."""
        self.trade_sizes.append(volume)

        if len(self.trade_sizes) < 50:
            return WhaleSignal()

        avg_size = float(np.mean(list(self.trade_sizes)))
        threshold = avg_size * self.multiplier

        # Prune old whale events
        cutoff = timestamp - self.window_s
        while self.whale_events and self.whale_events[0].timestamp < cutoff:
            self.whale_events.popleft()

        whale_detected = volume >= threshold
        latest_event = None

        if whale_detected:
            # Classify: momentum or spoof?
            # High ghost count + high spoof score → likely spoofing → fade
            manipulation_score = ghost_count / 10.0 * 0.5 + spoof_score * 0.5

            if manipulation_score > 0.5:
                classification = "spoof_fade"
                confidence = min(manipulation_score, 1.0)
            else:
                classification = "momentum"
                confidence = max(1.0 - manipulation_score, 0.5)

            latest_event = WhaleEvent(
                timestamp=timestamp,
                price=price,
                volume=volume,
                is_buy=is_buy,
                classification=classification,
                confidence=confidence,
            )
            self.whale_events.append(latest_event)

        # Aggregate recent whale direction
        net = 0.0
        total_vol = 0.0
        for ev in self.whale_events:
            direction = 1.0 if ev.is_buy else -1.0
            if ev.classification == "spoof_fade":
                direction *= -1  # fade the apparent direction
            weight = ev.volume * ev.confidence
            net += direction * weight
            total_vol += ev.volume

        net_direction = net / (total_vol + 1e-10) if total_vol > 0 else 0.0

        return WhaleSignal(
            whale_detected=whale_detected,
            latest_event=latest_event,
            recent_count=len(self.whale_events),
            net_direction=float(np.clip(net_direction, -1.0, 1.0)),
            total_whale_volume=total_vol,
        )
