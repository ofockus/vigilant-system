"""
Native Bybit v5 WebSocket client.

Secondary exchange — used for liquidity comparison, funding rate divergence,
or fallback execution. Same auto-reconnect + orderbook maintenance pattern.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Any

import aiohttp
import orjson
from loguru import logger

BYBIT_WS_PUBLIC = "wss://stream.bybit.com/v5/public/linear"
BYBIT_WS_PRIVATE = "wss://stream.bybit.com/v5/private"
BYBIT_REST = "https://api.bybit.com"
BYBIT_WS_PUBLIC_TESTNET = "wss://stream-testnet.bybit.com/v5/public/linear"
BYBIT_WS_PRIVATE_TESTNET = "wss://stream-testnet.bybit.com/v5/private"
BYBIT_REST_TESTNET = "https://api-testnet.bybit.com"


@dataclass
class BybitBook:
    bids: dict[float, float] = field(default_factory=dict)
    asks: dict[float, float] = field(default_factory=dict)
    timestamp: float = 0.0

    @property
    def best_bid(self) -> float:
        return max(self.bids.keys()) if self.bids else 0.0

    @property
    def best_ask(self) -> float:
        return min(self.asks.keys()) if self.asks else 0.0

    @property
    def mid(self) -> float:
        b, a = self.best_bid, self.best_ask
        return (b + a) / 2 if b and a else 0.0


class BybitWS:
    """Native Bybit v5 WebSocket for funding rates and cross-exchange data."""

    def __init__(
        self,
        api_key: str = "",
        api_secret: str = "",
        testnet: bool = False,
        symbols: list[str] | None = None,
    ) -> None:
        self.api_key = api_key
        self.api_secret = api_secret
        self.testnet = testnet
        self.symbols = symbols or ["BTCUSDT"]

        self._ws_pub = BYBIT_WS_PUBLIC_TESTNET if testnet else BYBIT_WS_PUBLIC
        self._ws_priv = BYBIT_WS_PRIVATE_TESTNET if testnet else BYBIT_WS_PRIVATE
        self._rest = BYBIT_REST_TESTNET if testnet else BYBIT_REST

        self.books: dict[str, BybitBook] = defaultdict(BybitBook)
        self.funding_rates: dict[str, float] = {}
        self.trades: dict[str, deque] = defaultdict(lambda: deque(maxlen=500))

        self._session: aiohttp.ClientSession | None = None
        self._running = False

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def fetch_funding_rates(self) -> dict[str, float]:
        """Fetch current funding rates for all symbols."""
        session = await self._get_session()
        rates = {}
        for sym in self.symbols:
            try:
                url = f"{self._rest}/v5/market/tickers"
                async with session.get(url, params={"category": "linear", "symbol": sym}) as resp:
                    data = await resp.json()
                    items = data.get("result", {}).get("list", [])
                    if items:
                        rates[sym] = float(items[0].get("fundingRate", 0))
            except Exception as e:
                logger.debug("Bybit funding fetch failed for {}: {}", sym, e)
        self.funding_rates = rates
        return rates

    async def _ws_loop(self) -> None:
        delay = 1.0
        while self._running:
            try:
                session = await self._get_session()
                async with session.ws_connect(self._ws_pub, heartbeat=20) as ws:
                    # Subscribe to orderbook and trades
                    topics = []
                    for sym in self.symbols:
                        topics.append(f"orderbook.50.{sym}")
                        topics.append(f"publicTrade.{sym}")

                    await ws.send_json({"op": "subscribe", "args": topics})
                    logger.info("Bybit WS connected | {} topics", len(topics))
                    delay = 1.0

                    async for msg in ws:
                        if not self._running:
                            break
                        if msg.type == aiohttp.WSMsgType.TEXT:
                            data = orjson.loads(msg.data)
                            topic = data.get("topic", "")

                            if "orderbook" in topic:
                                self._process_book(data)
                            elif "publicTrade" in topic:
                                self._process_trade(data)

            except Exception as e:
                logger.warning("Bybit WS error: {} — reconnecting in {:.0f}s", e, delay)

            if self._running:
                await asyncio.sleep(delay)
                delay = min(delay * 2, 30)

    def _process_book(self, data: dict) -> None:
        d = data.get("data", {})
        sym = d.get("s", "")
        book = self.books[sym]
        action = data.get("type", "")

        if action == "snapshot":
            book.bids = {float(p): float(q) for p, q in d.get("b", [])}
            book.asks = {float(p): float(q) for p, q in d.get("a", [])}
        elif action == "delta":
            for p, q in d.get("b", []):
                price, qty = float(p), float(q)
                if qty == 0:
                    book.bids.pop(price, None)
                else:
                    book.bids[price] = qty
            for p, q in d.get("a", []):
                price, qty = float(p), float(q)
                if qty == 0:
                    book.asks.pop(price, None)
                else:
                    book.asks[price] = qty

        book.timestamp = time.time()

    def _process_trade(self, data: dict) -> None:
        for t in data.get("data", []):
            sym = t.get("s", "")
            self.trades[sym].append({
                "price": float(t.get("p", 0)),
                "qty": float(t.get("v", 0)),
                "side": t.get("S", ""),
                "timestamp": float(t.get("T", 0)) / 1000.0,
            })

    async def start(self) -> None:
        self._running = True
        asyncio.create_task(self._ws_loop(), name="bybit_ws")
        logger.info("Bybit WS started | {} symbols", len(self.symbols))

    async def stop(self) -> None:
        self._running = False
        if self._session and not self._session.closed:
            await self._session.close()
