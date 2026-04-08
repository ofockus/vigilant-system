"""
L5: Cross-Exchange Funding Divergence.

Compares funding rates between Binance and Bybit (public APIs).
Large divergence signals arbitrage pressure or directional conviction.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

import httpx
from loguru import logger


@dataclass
class CrossIntelSignal:
    binance_funding: float = 0.0
    bybit_funding: float = 0.0
    divergence: float = 0.0       # absolute difference
    direction_bias: float = 0.0   # positive = long bias from funding
    stale: bool = True            # True if data is outdated


class CrossIntelEngine:
    """L5 signal layer: cross-exchange funding rate divergence."""

    BINANCE_URL = "https://fapi.binance.com/fapi/v1/premiumIndex"
    BYBIT_URL = "https://api.bybit.com/v5/market/tickers"
    REFRESH_INTERVAL = 300  # 5 minutes

    def __init__(self, enabled: bool = True) -> None:
        self.enabled = enabled
        self._last_fetch: float = 0.0
        self._signal = CrossIntelSignal()
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=10.0)
        return self._client

    async def fetch(self) -> CrossIntelSignal:
        if not self.enabled:
            return CrossIntelSignal(stale=True)

        now = time.time()
        if now - self._last_fetch < self.REFRESH_INTERVAL:
            return self._signal

        client = await self._get_client()
        binance_rate = 0.0
        bybit_rate = 0.0
        stale = True

        try:
            resp = await client.get(self.BINANCE_URL, params={"symbol": "BTCUSDT"})
            if resp.status_code == 200:
                data = resp.json()
                binance_rate = float(data.get("lastFundingRate", 0))
                stale = False
        except Exception as e:
            logger.debug("Binance funding fetch failed: {}", e)

        try:
            resp = await client.get(
                self.BYBIT_URL,
                params={"category": "linear", "symbol": "BTCUSDT"},
            )
            if resp.status_code == 200:
                items = resp.json().get("result", {}).get("list", [])
                if items:
                    bybit_rate = float(items[0].get("fundingRate", 0))
                    stale = False
        except Exception as e:
            logger.debug("Bybit funding fetch failed: {}", e)

        divergence = abs(binance_rate - bybit_rate)

        # Direction bias: if Binance funding is higher, shorts are paying longs → long bias
        avg_funding = (binance_rate + bybit_rate) / 2
        if avg_funding > 0.0005:
            direction_bias = -0.3  # high positive funding → crowded longs → short bias
        elif avg_funding < -0.0005:
            direction_bias = 0.3   # negative funding → crowded shorts → long bias
        else:
            direction_bias = 0.0

        # Amplify if divergence is large
        if divergence > 0.001:
            direction_bias *= 1.5

        self._signal = CrossIntelSignal(
            binance_funding=binance_rate,
            bybit_funding=bybit_rate,
            divergence=divergence,
            direction_bias=float(max(min(direction_bias, 1.0), -1.0)),
            stale=stale,
        )
        self._last_fetch = now
        return self._signal

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()
