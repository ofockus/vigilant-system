"""
Async ccxt Binance connector.

Handles both Spot and Futures via ccxt.pro for WebSocket streams.
Provides unified interface for market data and order execution.
Supports testnet and mainnet with automatic URL switching.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Callable

import ccxt.async_support as ccxt
from loguru import logger


@dataclass
class TickData:
    timestamp: float = 0.0
    price: float = 0.0
    volume_24h: float = 0.0
    bid: float = 0.0
    ask: float = 0.0
    spread: float = 0.0


@dataclass
class TradeData:
    timestamp: float = 0.0
    price: float = 0.0
    amount: float = 0.0
    is_buy: bool = True


@dataclass
class OrderBookData:
    timestamp: float = 0.0
    bids: list[list[float]] = field(default_factory=list)
    asks: list[list[float]] = field(default_factory=list)


class BinanceConnector:
    """Async Binance connector via ccxt."""

    def __init__(
        self,
        api_key: str,
        api_secret: str,
        testnet: bool = True,
        market_type: str = "future",
    ) -> None:
        self.testnet = testnet
        self.market_type = market_type

        options: dict[str, Any] = {"defaultType": market_type}

        exchange_class = ccxt.binanceusdm if market_type == "future" else ccxt.binance

        self.exchange: ccxt.Exchange = exchange_class(
            {
                "apiKey": api_key,
                "secret": api_secret,
                "sandbox": testnet,
                "enableRateLimit": True,
                "options": options,
            }
        )

        self._trade_callbacks: list[Callable] = []
        self._running = False
        logger.info(
            "Connector initialized | testnet={} type={}", testnet, market_type
        )

    async def start(self) -> None:
        """Load markets."""
        await self.exchange.load_markets()
        self._running = True
        logger.info(
            "Markets loaded | {} pairs available", len(self.exchange.markets)
        )

    async def stop(self) -> None:
        """Close exchange connection."""
        self._running = False
        await self.exchange.close()
        logger.info("Connector stopped")

    async def fetch_ticker(self, symbol: str) -> TickData:
        ticker = await self.exchange.fetch_ticker(symbol)
        bid = ticker.get("bid") or 0.0
        ask = ticker.get("ask") or 0.0
        return TickData(
            timestamp=time.time(),
            price=ticker.get("last") or 0.0,
            volume_24h=ticker.get("quoteVolume") or 0.0,
            bid=bid,
            ask=ask,
            spread=(ask - bid) / bid * 100 if bid > 0 else 0.0,
        )

    async def fetch_orderbook(self, symbol: str, limit: int = 20) -> OrderBookData:
        book = await self.exchange.fetch_order_book(symbol, limit)
        return OrderBookData(
            timestamp=time.time(),
            bids=book.get("bids", []),
            asks=book.get("asks", []),
        )

    async def fetch_recent_trades(self, symbol: str, limit: int = 100) -> list[TradeData]:
        trades = await self.exchange.fetch_trades(symbol, limit=limit)
        return [
            TradeData(
                timestamp=t["timestamp"] / 1000.0 if t.get("timestamp") else time.time(),
                price=t.get("price", 0.0),
                amount=t.get("amount", 0.0),
                is_buy=t.get("side") == "buy",
            )
            for t in trades
        ]

    async def watch_trades(self, symbol: str) -> AsyncIterator[TradeData]:
        """Stream trades via WebSocket (ccxt pro). Falls back to polling if unavailable."""
        if hasattr(self.exchange, "watch_trades"):
            while self._running:
                try:
                    trades = await self.exchange.watch_trades(symbol)
                    for t in trades:
                        yield TradeData(
                            timestamp=t["timestamp"] / 1000.0 if t.get("timestamp") else time.time(),
                            price=t.get("price", 0.0),
                            amount=t.get("amount", 0.0),
                            is_buy=t.get("side") == "buy",
                        )
                except Exception as e:
                    logger.warning("WebSocket trade stream error: {}", e)
                    await asyncio.sleep(1)
        else:
            # Polling fallback
            logger.info("WebSocket not available, using polling fallback")
            while self._running:
                try:
                    trades = await self.fetch_recent_trades(symbol, limit=50)
                    for t in trades:
                        yield t
                except Exception as e:
                    logger.warning("Trade polling error: {}", e)
                await asyncio.sleep(1)

    async def watch_orderbook(self, symbol: str) -> AsyncIterator[OrderBookData]:
        """Stream orderbook via WebSocket. Falls back to polling."""
        if hasattr(self.exchange, "watch_order_book"):
            while self._running:
                try:
                    book = await self.exchange.watch_order_book(symbol)
                    yield OrderBookData(
                        timestamp=time.time(),
                        bids=book.get("bids", []),
                        asks=book.get("asks", []),
                    )
                except Exception as e:
                    logger.warning("WebSocket orderbook error: {}", e)
                    await asyncio.sleep(1)
        else:
            while self._running:
                try:
                    yield await self.fetch_orderbook(symbol)
                except Exception as e:
                    logger.warning("Orderbook polling error: {}", e)
                await asyncio.sleep(2)

    # --- Order execution ---

    async def create_market_order(
        self, symbol: str, side: str, amount: float
    ) -> dict[str, Any]:
        """Place a market order. Returns order info dict."""
        logger.info("Market order | {} {} {:.6f}", side.upper(), symbol, amount)
        order = await self.exchange.create_order(
            symbol=symbol,
            type="market",
            side=side,
            amount=amount,
        )
        return order

    async def set_leverage(self, symbol: str, leverage: int) -> None:
        """Set leverage for futures."""
        if self.market_type == "future":
            try:
                await self.exchange.set_leverage(leverage, symbol)
                logger.info("Leverage set to {}x for {}", leverage, symbol)
            except Exception as e:
                logger.warning("Failed to set leverage: {}", e)

    async def fetch_balance(self) -> dict[str, float]:
        """Fetch account balance. Returns {currency: free_amount}."""
        balance = await self.exchange.fetch_balance()
        return {
            "USDT": balance.get("USDT", {}).get("free", 0.0),
            "total_USDT": balance.get("USDT", {}).get("total", 0.0),
        }

    async def fetch_positions(self, symbol: str) -> list[dict[str, Any]]:
        """Fetch open positions for symbol."""
        if self.market_type != "future":
            return []
        try:
            positions = await self.exchange.fetch_positions([symbol])
            return [
                {
                    "symbol": p.get("symbol"),
                    "side": p.get("side"),
                    "contracts": p.get("contracts", 0),
                    "notional": p.get("notional", 0),
                    "unrealizedPnl": p.get("unrealizedPnl", 0),
                    "entryPrice": p.get("entryPrice", 0),
                    "leverage": p.get("leverage", 1),
                }
                for p in positions
                if p.get("contracts", 0) != 0
            ]
        except Exception as e:
            logger.warning("Failed to fetch positions: {}", e)
            return []
