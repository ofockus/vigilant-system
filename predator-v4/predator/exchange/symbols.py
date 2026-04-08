"""
Dynamic symbol selector — auto-picks the most liquid/volatile pairs.

Refreshes periodically from 24h ticker data. Filters by volume and volatility.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

from loguru import logger


class SymbolSelector:
    """Auto-select top symbols by volume * volatility score."""

    def __init__(
        self,
        pool: list[str],
        max_active: int = 6,
        min_volume: float = 50_000_000,
        min_volatility: float = 0.0003,
        refresh_s: int = 300,
    ) -> None:
        self.pool = [s.upper() for s in pool]
        self.max_active = max_active
        self.min_volume = min_volume
        self.min_volatility = min_volatility
        self.refresh_s = refresh_s
        self.active: list[str] = []
        self._last_refresh = 0.0

    async def refresh(self, fetch_tickers_fn: Any) -> list[str]:
        """Re-rank symbols and return the active set."""
        now = time.time()
        if now - self._last_refresh < self.refresh_s and self.active:
            return self.active

        try:
            tickers = await fetch_tickers_fn()
            scored = []

            for t in tickers:
                sym = t.get("symbol", "")
                if sym not in self.pool:
                    continue

                vol = float(t.get("quoteVolume", 0))
                high = float(t.get("highPrice", 0))
                low = float(t.get("lowPrice", 0))
                close = float(t.get("lastPrice", 1))

                if vol < self.min_volume:
                    continue

                volatility = (high - low) / close if close > 0 else 0
                if volatility < self.min_volatility:
                    continue

                # Score: volume-weighted volatility
                score = vol * volatility
                scored.append((sym, score, vol, volatility))

            scored.sort(key=lambda x: -x[1])
            self.active = [s[0] for s in scored[:self.max_active]]
            self._last_refresh = now

            logger.info("Symbol refresh | active={} | top: {}",
                       len(self.active),
                       [(s[0], f"${s[2]/1e6:.0f}M", f"{s[3]*100:.2f}%") for s in scored[:self.max_active]])

        except Exception as e:
            logger.error("Symbol refresh failed: {}", e)
            if not self.active:
                self.active = self.pool[:self.max_active]

        return self.active
