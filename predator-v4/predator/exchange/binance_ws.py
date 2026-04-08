"""
Native Binance Futures WebSocket client.

Direct websocket connection — no ccxt overhead. Handles:
- Combined stream for multiple symbols (depth@100ms, aggTrade, kline_1s)
- User data stream (account updates, order fills)
- Auto-reconnect with exponential backoff
- Zero-copy orderbook maintenance (local diff updates)
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Any, Callable, Coroutine

import aiohttp
import orjson
from loguru import logger

FUTURES_WS = "wss://fstream.binance.com"
FUTURES_WS_TESTNET = "wss://stream.binancefuture.com"
FUTURES_REST = "https://fapi.binance.com"
FUTURES_REST_TESTNET = "https://testnet.binancefuture.com"


@dataclass
class OrderBookLevel:
    price: float
    qty: float


@dataclass
class LocalBook:
    """Locally maintained orderbook from diff stream."""
    bids: dict[float, float] = field(default_factory=dict)
    asks: dict[float, float] = field(default_factory=dict)
    last_update_id: int = 0
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

    @property
    def spread_pct(self) -> float:
        b, a = self.best_bid, self.best_ask
        return (a - b) / b * 100 if b > 0 else 0.0

    def top_bids(self, n: int = 20) -> list[tuple[float, float]]:
        return sorted(self.bids.items(), key=lambda x: -x[0])[:n]

    def top_asks(self, n: int = 20) -> list[tuple[float, float]]:
        return sorted(self.asks.items(), key=lambda x: x[0])[:n]


@dataclass
class AggTrade:
    symbol: str
    price: float
    qty: float
    is_buyer_maker: bool
    timestamp: float
    trade_id: int


class BinanceWS:
    """Native Binance Futures WebSocket with auto-reconnect."""

    def __init__(
        self,
        api_key: str,
        api_secret: str,
        testnet: bool = False,
        symbols: list[str] | None = None,
    ) -> None:
        self.api_key = api_key
        self.api_secret = api_secret
        self.testnet = testnet
        self.symbols = [s.lower() for s in (symbols or ["btcusdt"])]

        self._ws_base = FUTURES_WS_TESTNET if testnet else FUTURES_WS
        self._rest_base = FUTURES_REST_TESTNET if testnet else FUTURES_REST

        # Data stores
        self.books: dict[str, LocalBook] = defaultdict(LocalBook)
        self.trades: dict[str, deque[AggTrade]] = defaultdict(lambda: deque(maxlen=2000))
        self.klines_1s: dict[str, deque[dict]] = defaultdict(lambda: deque(maxlen=300))

        # Callbacks
        self._on_trade: list[Callable[..., Coroutine]] = []
        self._on_book: list[Callable[..., Coroutine]] = []

        # State
        self._session: aiohttp.ClientSession | None = None
        self._running = False
        self._listen_key: str = ""
        self._reconnect_delay = 1.0

    def on_trade(self, cb: Callable[..., Coroutine]) -> None:
        self._on_trade.append(cb)

    def on_book_update(self, cb: Callable[..., Coroutine]) -> None:
        self._on_book.append(cb)

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                json_serialize=lambda x: orjson.dumps(x).decode()
            )
        return self._session

    def _sign(self, params: dict) -> dict:
        params["timestamp"] = int(time.time() * 1000)
        query = "&".join(f"{k}={v}" for k, v in sorted(params.items()))
        sig = hmac.new(
            self.api_secret.encode(), query.encode(), hashlib.sha256
        ).hexdigest()
        params["signature"] = sig
        return params

    async def _rest_get(self, path: str, params: dict | None = None, signed: bool = False) -> Any:
        session = await self._get_session()
        params = params or {}
        headers = {"X-MBX-APIKEY": self.api_key}
        if signed:
            params = self._sign(params)
        url = f"{self._rest_base}{path}"
        async with session.get(url, params=params, headers=headers) as resp:
            return await resp.json()

    async def _rest_post(self, path: str, params: dict | None = None) -> Any:
        session = await self._get_session()
        params = self._sign(params or {})
        headers = {"X-MBX-APIKEY": self.api_key}
        url = f"{self._rest_base}{path}"
        async with session.post(url, params=params, headers=headers) as resp:
            return await resp.json()

    async def _rest_delete(self, path: str, params: dict | None = None) -> Any:
        session = await self._get_session()
        params = self._sign(params or {})
        headers = {"X-MBX-APIKEY": self.api_key}
        url = f"{self._rest_base}{path}"
        async with session.delete(url, params=params, headers=headers) as resp:
            return await resp.json()

    async def _get_listen_key(self) -> str:
        data = await self._rest_post("/fapi/v1/listenKey")
        return data.get("listenKey", "")

    async def _keepalive_listen_key(self) -> None:
        while self._running:
            try:
                await self._rest_post("/fapi/v1/listenKey")
            except Exception as e:
                logger.warning("Listen key keepalive failed: {}", e)
            await asyncio.sleep(1800)  # every 30 min

    # --- Public REST for snapshots ---

    async def fetch_book_snapshot(self, symbol: str, limit: int = 50) -> dict:
        return await self._rest_get(
            "/fapi/v1/depth",
            {"symbol": symbol.upper(), "limit": limit},
        )

    async def fetch_ticker_24h(self, symbol: str) -> dict:
        return await self._rest_get(
            "/fapi/v1/ticker/24hr",
            {"symbol": symbol.upper()},
        )

    async def fetch_all_tickers(self) -> list[dict]:
        return await self._rest_get("/fapi/v1/ticker/24hr")

    async def fetch_klines(self, symbol: str, interval: str = "1m",
                           limit: int = 500) -> list[list]:
        return await self._rest_get(
            "/fapi/v1/klines",
            {"symbol": symbol.upper(), "interval": interval, "limit": limit},
        )

    async def fetch_agg_trades(self, symbol: str, limit: int = 1000) -> list[dict]:
        return await self._rest_get(
            "/fapi/v1/aggTrades",
            {"symbol": symbol.upper(), "limit": limit},
        )

    # --- Order execution (native, no ccxt) ---

    async def place_market_order(self, symbol: str, side: str, quantity: float,
                                  reduce_only: bool = False) -> dict:
        params: dict[str, Any] = {
            "symbol": symbol.upper(),
            "side": side.upper(),
            "type": "MARKET",
            "quantity": f"{quantity:.8f}".rstrip("0").rstrip("."),
        }
        if reduce_only:
            params["reduceOnly"] = "true"
        return await self._rest_post("/fapi/v1/order", params)

    async def place_limit_order(self, symbol: str, side: str, quantity: float,
                                 price: float, time_in_force: str = "GTC") -> dict:
        params: dict[str, Any] = {
            "symbol": symbol.upper(),
            "side": side.upper(),
            "type": "LIMIT",
            "quantity": f"{quantity:.8f}".rstrip("0").rstrip("."),
            "price": f"{price:.8f}".rstrip("0").rstrip("."),
            "timeInForce": time_in_force,
        }
        return await self._rest_post("/fapi/v1/order", params)

    async def cancel_order(self, symbol: str, order_id: int) -> dict:
        return await self._rest_delete(
            "/fapi/v1/order",
            {"symbol": symbol.upper(), "orderId": order_id},
        )

    async def set_leverage(self, symbol: str, leverage: int) -> dict:
        return await self._rest_post(
            "/fapi/v1/leverage",
            {"symbol": symbol.upper(), "leverage": leverage},
        )

    async def fetch_account(self) -> dict:
        return await self._rest_get("/fapi/v2/account", signed=True)

    async def fetch_positions(self) -> list[dict]:
        data = await self._rest_get("/fapi/v2/positionRisk", signed=True)
        return [p for p in data if float(p.get("positionAmt", 0)) != 0]

    # --- WebSocket streams ---

    def _build_stream_url(self) -> str:
        streams = []
        for s in self.symbols:
            streams.append(f"{s}@depth@100ms")
            streams.append(f"{s}@aggTrade")
            streams.append(f"{s}@kline_1s")
        combined = "/".join(streams)
        return f"{self._ws_base}/stream?streams={combined}"

    async def _init_books(self) -> None:
        """Fetch initial orderbook snapshots for all symbols."""
        for sym in self.symbols:
            try:
                snap = await self.fetch_book_snapshot(sym.upper(), limit=50)
                book = self.books[sym]
                book.bids = {float(p): float(q) for p, q in snap.get("bids", [])}
                book.asks = {float(p): float(q) for p, q in snap.get("asks", [])}
                book.last_update_id = snap.get("lastUpdateId", 0)
                book.timestamp = time.time()
                logger.debug("Book snapshot loaded: {} ({} bids, {} asks)",
                             sym, len(book.bids), len(book.asks))
            except Exception as e:
                logger.warning("Book snapshot failed for {}: {}", sym, e)

    def _process_depth(self, data: dict) -> None:
        sym = data.get("s", "").lower()
        book = self.books[sym]

        for price_s, qty_s in data.get("b", []):
            price, qty = float(price_s), float(qty_s)
            if qty == 0:
                book.bids.pop(price, None)
            else:
                book.bids[price] = qty

        for price_s, qty_s in data.get("a", []):
            price, qty = float(price_s), float(qty_s)
            if qty == 0:
                book.asks.pop(price, None)
            else:
                book.asks[price] = qty

        book.last_update_id = data.get("u", book.last_update_id)
        book.timestamp = time.time()

    def _process_agg_trade(self, data: dict) -> AggTrade:
        trade = AggTrade(
            symbol=data.get("s", "").lower(),
            price=float(data.get("p", 0)),
            qty=float(data.get("q", 0)),
            is_buyer_maker=data.get("m", False),
            timestamp=data.get("T", 0) / 1000.0,
            trade_id=data.get("a", 0),
        )
        self.trades[trade.symbol].append(trade)
        return trade

    def _process_kline(self, data: dict) -> None:
        k = data.get("k", {})
        sym = data.get("s", "").lower()
        self.klines_1s[sym].append({
            "t": k.get("t", 0) / 1000.0,
            "o": float(k.get("o", 0)),
            "h": float(k.get("h", 0)),
            "l": float(k.get("l", 0)),
            "c": float(k.get("c", 0)),
            "v": float(k.get("V", 0)),  # taker buy base vol
            "closed": k.get("x", False),
        })

    async def _ws_loop(self) -> None:
        """Main WebSocket event loop with auto-reconnect."""
        url = self._build_stream_url()
        self._reconnect_delay = 1.0

        while self._running:
            try:
                session = await self._get_session()
                async with session.ws_connect(url, heartbeat=20) as ws:
                    logger.info("WS connected to {}", url[:80])
                    self._reconnect_delay = 1.0

                    async for msg in ws:
                        if not self._running:
                            break
                        if msg.type == aiohttp.WSMsgType.TEXT:
                            await self._handle_message(orjson.loads(msg.data))
                        elif msg.type in (aiohttp.WSMsgType.ERROR, aiohttp.WSMsgType.CLOSED):
                            break

            except Exception as e:
                logger.warning("WS error: {} — reconnecting in {:.0f}s", e, self._reconnect_delay)

            if self._running:
                await asyncio.sleep(self._reconnect_delay)
                self._reconnect_delay = min(self._reconnect_delay * 2, 30)

    async def _handle_message(self, msg: dict) -> None:
        stream = msg.get("stream", "")
        data = msg.get("data", {})
        event = data.get("e", "")

        if event == "depthUpdate":
            self._process_depth(data)
            for cb in self._on_book:
                try:
                    await cb(data.get("s", "").lower(), self.books[data.get("s", "").lower()])
                except Exception as e:
                    logger.error("Book callback error: {}", e)

        elif event == "aggTrade":
            trade = self._process_agg_trade(data)
            for cb in self._on_trade:
                try:
                    await cb(trade)
                except Exception as e:
                    logger.error("Trade callback error: {}", e)

        elif event == "kline":
            self._process_kline(data)

    # --- User data stream ---

    async def _user_data_loop(self) -> None:
        if not self.api_key:
            return

        while self._running:
            try:
                self._listen_key = await self._get_listen_key()
                if not self._listen_key:
                    await asyncio.sleep(5)
                    continue

                url = f"{self._ws_base}/ws/{self._listen_key}"
                session = await self._get_session()
                async with session.ws_connect(url, heartbeat=20) as ws:
                    logger.info("User data stream connected")
                    async for msg in ws:
                        if not self._running:
                            break
                        if msg.type == aiohttp.WSMsgType.TEXT:
                            data = orjson.loads(msg.data)
                            event = data.get("e", "")
                            if event == "ORDER_TRADE_UPDATE":
                                logger.info("Order update: {}", data.get("o", {}).get("S", ""))
            except Exception as e:
                logger.warning("User data stream error: {}", e)
                await asyncio.sleep(5)

    # --- Lifecycle ---

    async def start(self) -> None:
        self._running = True
        await self._init_books()
        asyncio.create_task(self._ws_loop(), name="binance_ws")
        asyncio.create_task(self._user_data_loop(), name="binance_userdata")
        asyncio.create_task(self._keepalive_listen_key(), name="binance_keepalive")
        logger.info("Binance WS started | {} symbols | testnet={}",
                     len(self.symbols), self.testnet)

    async def stop(self) -> None:
        self._running = False
        if self._session and not self._session.closed:
            await self._session.close()
        logger.info("Binance WS stopped")
