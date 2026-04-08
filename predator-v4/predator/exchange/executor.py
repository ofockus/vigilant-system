"""
Order executor with paper/live modes.

Paper mode: simulated fills with realistic slippage.
Live mode: native Binance REST (sub-5ms with Tokyo VPS).
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from loguru import logger


@dataclass
class FillResult:
    success: bool = False
    order_id: str = ""
    symbol: str = ""
    side: str = ""
    qty: float = 0.0
    price: float = 0.0
    fee: float = 0.0
    latency_ms: float = 0.0
    timestamp: float = 0.0
    mode: str = "paper"


class Executor:
    """Handles order placement in paper or live mode."""

    def __init__(
        self,
        mode: str,
        binance: Any,  # BinanceWS instance
        taker_fee_pct: float = 0.04,
        slippage_pct: float = 0.005,
    ) -> None:
        self.mode = mode
        self.binance = binance
        self.taker_fee_pct = taker_fee_pct
        self.slippage_pct = slippage_pct
        self._order_counter = 0

    async def market_entry(self, symbol: str, side: str, qty: float,
                           current_price: float) -> FillResult:
        """Execute market entry order."""
        t0 = time.time()

        if self.mode == "paper":
            return self._paper_fill(symbol, side, qty, current_price, t0)

        elif self.mode == "live":
            return await self._live_fill(symbol, side, qty, t0)

        # observe mode
        return FillResult(
            success=True, symbol=symbol, side=side, qty=qty,
            price=current_price, timestamp=t0, mode="observe",
        )

    async def market_exit(self, symbol: str, side: str, qty: float,
                          current_price: float) -> FillResult:
        """Execute market exit (close position)."""
        close_side = "SELL" if side == "BUY" else "BUY"
        t0 = time.time()

        if self.mode == "paper":
            return self._paper_fill(symbol, close_side, qty, current_price, t0)

        elif self.mode == "live":
            return await self._live_fill(symbol, close_side, qty, t0, reduce_only=True)

        return FillResult(
            success=True, symbol=symbol, side=close_side, qty=qty,
            price=current_price, timestamp=t0, mode="observe",
        )

    def _paper_fill(self, symbol: str, side: str, qty: float,
                    price: float, t0: float) -> FillResult:
        """Simulate fill with slippage and fees."""
        self._order_counter += 1
        slip = self.slippage_pct / 100
        fill_price = price * (1 + slip) if side == "BUY" else price * (1 - slip)
        fee = qty * fill_price * self.taker_fee_pct / 100

        return FillResult(
            success=True,
            order_id=f"PAPER-{self._order_counter}",
            symbol=symbol,
            side=side,
            qty=qty,
            price=fill_price,
            fee=fee,
            latency_ms=(time.time() - t0) * 1000,
            timestamp=time.time(),
            mode="paper",
        )

    async def _live_fill(self, symbol: str, side: str, qty: float,
                         t0: float, reduce_only: bool = False) -> FillResult:
        """Execute via native Binance REST."""
        try:
            result = await self.binance.place_market_order(
                symbol=symbol, side=side, quantity=qty, reduce_only=reduce_only
            )

            if "orderId" not in result:
                logger.error("Order failed: {}", result)
                return FillResult(success=False, symbol=symbol, side=side,
                                  latency_ms=(time.time() - t0) * 1000)

            avg_price = float(result.get("avgPrice", 0))
            filled_qty = float(result.get("executedQty", 0))

            return FillResult(
                success=True,
                order_id=str(result["orderId"]),
                symbol=symbol,
                side=side,
                qty=filled_qty,
                price=avg_price,
                fee=filled_qty * avg_price * self.taker_fee_pct / 100,
                latency_ms=(time.time() - t0) * 1000,
                timestamp=time.time(),
                mode="live",
            )

        except Exception as e:
            logger.error("Live order failed: {}", e)
            return FillResult(success=False, symbol=symbol, side=side,
                              latency_ms=(time.time() - t0) * 1000)
