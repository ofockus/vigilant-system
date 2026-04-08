"""
Feature engineering for PREDATOR v4.

Computes real-time features from orderbook + trade stream data:
- Order flow imbalance (multi-level book pressure)
- Volume delta (aggressive buy vs sell)
- DECEL (momentum deceleration)
- EK_REV (kinetic energy reversal)
- Spread dynamics
- Multi-timeframe price returns (1s, 5s, 15s)
- Micro-volatility (ATR proxy)
"""

from __future__ import annotations

import math
import time
from collections import deque
from dataclasses import dataclass, field

import numpy as np


@dataclass
class FeatureVector:
    """Complete feature set for one tick/symbol."""
    timestamp: float = 0.0
    symbol: str = ""

    # Order flow
    book_imbalance_1: float = 0.0    # top 1 level bid/ask imbalance
    book_imbalance_5: float = 0.0    # top 5 levels
    book_imbalance_20: float = 0.0   # top 20 levels
    book_pressure: float = 0.0       # weighted depth pressure

    # Volume delta
    flow_delta: float = 0.0          # net aggressive buy - sell
    flow_intensity: float = 0.0      # volume vs average
    cvd: float = 0.0                 # cumulative volume delta

    # Momentum
    decel: float = 0.0               # momentum deceleration [-1, 1]
    velocity: float = 0.0            # price velocity
    acceleration: float = 0.0        # price acceleration
    ek: float = 0.0                  # kinetic energy
    ek_rev: float = 0.0              # KE reversal signal

    # Spread
    spread_pct: float = 0.0          # current spread
    spread_z: float = 0.0            # spread z-score vs EMA

    # Multi-timeframe returns
    ret_1s: float = 0.0
    ret_5s: float = 0.0
    ret_15s: float = 0.0

    # Volatility
    micro_vol: float = 0.0           # 30s realized vol
    atr_proxy: float = 0.0           # ATR-like from 1s klines

    # Funding
    funding_rate: float = 0.0
    funding_divergence: float = 0.0  # binance vs bybit

    def to_array(self) -> np.ndarray:
        """Convert to numpy array for ML inference."""
        return np.array([
            self.book_imbalance_1, self.book_imbalance_5, self.book_imbalance_20,
            self.book_pressure, self.flow_delta, self.flow_intensity, self.cvd,
            self.decel, self.velocity, self.acceleration, self.ek, self.ek_rev,
            self.spread_pct, self.spread_z, self.ret_1s, self.ret_5s, self.ret_15s,
            self.micro_vol, self.atr_proxy, self.funding_rate, self.funding_divergence,
        ], dtype=np.float64)

    @staticmethod
    def feature_names() -> list[str]:
        return [
            "book_imb_1", "book_imb_5", "book_imb_20", "book_pressure",
            "flow_delta", "flow_intensity", "cvd",
            "decel", "velocity", "acceleration", "ek", "ek_rev",
            "spread_pct", "spread_z", "ret_1s", "ret_5s", "ret_15s",
            "micro_vol", "atr_proxy", "funding_rate", "funding_div",
        ]


class FeatureEngine:
    """Real-time feature computation from raw market data."""

    def __init__(self, momentum_window: int = 50, flow_window: int = 100,
                 spread_ema_alpha: float = 0.05) -> None:
        self.mom_window = momentum_window
        self.flow_window = flow_window
        self.spread_alpha = spread_ema_alpha

        # Per-symbol state
        self._prices: dict[str, deque] = {}
        self._times: dict[str, deque] = {}
        self._velocities: dict[str, deque] = {}
        self._buy_vol: dict[str, deque] = {}
        self._sell_vol: dict[str, deque] = {}
        self._cvd: dict[str, float] = {}
        self._spread_ema: dict[str, float] = {}
        self._spread_var: dict[str, float] = {}
        self._kline_closes: dict[str, deque] = {}
        self._kline_ranges: dict[str, deque] = {}

    def _ensure_sym(self, sym: str) -> None:
        if sym not in self._prices:
            self._prices[sym] = deque(maxlen=500)
            self._times[sym] = deque(maxlen=500)
            self._velocities[sym] = deque(maxlen=200)
            self._buy_vol[sym] = deque(maxlen=self.flow_window)
            self._sell_vol[sym] = deque(maxlen=self.flow_window)
            self._cvd[sym] = 0.0
            self._spread_ema[sym] = 0.0
            self._spread_var[sym] = 0.0
            self._kline_closes[sym] = deque(maxlen=60)
            self._kline_ranges[sym] = deque(maxlen=60)

    def add_trade(self, sym: str, price: float, qty: float,
                  is_buy: bool, ts: float) -> None:
        """Ingest a trade tick."""
        self._ensure_sym(sym)
        self._prices[sym].append(price)
        self._times[sym].append(ts)

        if is_buy:
            self._buy_vol[sym].append(qty)
            self._sell_vol[sym].append(0)
            self._cvd[sym] += qty
        else:
            self._buy_vol[sym].append(0)
            self._sell_vol[sym].append(qty)
            self._cvd[sym] -= qty

    def add_kline(self, sym: str, close: float, high: float, low: float) -> None:
        """Ingest a 1s kline close."""
        self._ensure_sym(sym)
        self._kline_closes[sym].append(close)
        self._kline_ranges[sym].append(high - low)

    def compute(self, sym: str, bids: list[tuple[float, float]],
                asks: list[tuple[float, float]], spread_pct: float,
                binance_funding: float = 0, bybit_funding: float = 0) -> FeatureVector:
        """Compute full feature vector for a symbol."""
        self._ensure_sym(sym)
        fv = FeatureVector(timestamp=time.time(), symbol=sym)
        prices = self._prices[sym]

        if len(prices) < 10:
            return fv

        # === ORDER FLOW IMBALANCE ===
        if bids and asks:
            # Top 1 level
            bid_qty_1 = bids[0][1] if bids else 0
            ask_qty_1 = asks[0][1] if asks else 0
            total_1 = bid_qty_1 + ask_qty_1
            fv.book_imbalance_1 = (bid_qty_1 - ask_qty_1) / total_1 if total_1 > 0 else 0

            # Top 5 levels
            bid_5 = sum(q for _, q in bids[:5])
            ask_5 = sum(q for _, q in asks[:5])
            total_5 = bid_5 + ask_5
            fv.book_imbalance_5 = (bid_5 - ask_5) / total_5 if total_5 > 0 else 0

            # Top 20 levels
            bid_20 = sum(q for _, q in bids[:20])
            ask_20 = sum(q for _, q in asks[:20])
            total_20 = bid_20 + ask_20
            fv.book_imbalance_20 = (bid_20 - ask_20) / total_20 if total_20 > 0 else 0

            # Weighted pressure (closer levels matter more)
            bp = 0.0
            for i, (_, q) in enumerate(bids[:10]):
                bp += q / (i + 1)
            ap = 0.0
            for i, (_, q) in enumerate(asks[:10]):
                ap += q / (i + 1)
            fv.book_pressure = (bp - ap) / (bp + ap + 1e-15)

        # === VOLUME DELTA ===
        buy_sum = sum(self._buy_vol[sym])
        sell_sum = sum(self._sell_vol[sym])
        total_flow = buy_sum + sell_sum
        fv.flow_delta = (buy_sum - sell_sum) / total_flow if total_flow > 0 else 0
        fv.flow_intensity = min(total_flow / (len(self._buy_vol[sym]) * 0.01 + 1e-10), 3.0) / 3.0
        fv.cvd = self._cvd[sym]

        # === MOMENTUM / DECEL / EK ===
        arr = np.array(list(prices)[-self.mom_window:])
        if len(arr) >= 5:
            # Velocity: EMA of returns
            rets = np.diff(arr) / arr[:-1] * 10000  # bps
            if len(rets) >= 3:
                weights = np.exp(np.linspace(-1, 0, len(rets)))
                weights /= weights.sum()
                velocity = float(np.sum(weights * rets))
                self._velocities[sym].append(velocity)
                fv.velocity = velocity

                # Acceleration
                vels = list(self._velocities[sym])
                if len(vels) >= 3:
                    fv.acceleration = vels[-1] - vels[-2]

                    # DECEL: velocity × acceleration < 0 means decelerating
                    if abs(velocity) > 0.01:
                        decel_raw = -velocity * fv.acceleration / (velocity ** 2 + 1e-10)
                        fv.decel = float(np.clip(decel_raw, -1, 1))

                # Kinetic energy: vol_weight * velocity^2
                fv.ek = fv.flow_intensity * velocity ** 2

                # EK reversal: KE dropping while velocity still high
                if len(vels) >= 5:
                    recent_ek = [fv.flow_intensity * v ** 2 for v in vels[-5:]]
                    if len(recent_ek) >= 3 and recent_ek[-3] > 0:
                        ek_change = (recent_ek[-1] - recent_ek[-3]) / (recent_ek[-3] + 1e-10)
                        fv.ek_rev = float(np.clip(-ek_change, -1, 1))

        # === SPREAD ===
        fv.spread_pct = spread_pct
        old_ema = self._spread_ema[sym]
        self._spread_ema[sym] += self.spread_alpha * (spread_pct - old_ema)
        self._spread_var[sym] += self.spread_alpha * (
            (spread_pct - self._spread_ema[sym]) ** 2 - self._spread_var[sym]
        )
        std = math.sqrt(max(self._spread_var[sym], 1e-15))
        fv.spread_z = (spread_pct - self._spread_ema[sym]) / std if std > 1e-10 else 0

        # === MULTI-TIMEFRAME RETURNS ===
        times = list(self._times[sym])
        price_arr = list(prices)
        now = time.time()
        for lookback, attr in [(1, "ret_1s"), (5, "ret_5s"), (15, "ret_15s")]:
            cutoff = now - lookback
            idx = None
            for i in range(len(times) - 1, -1, -1):
                if times[i] <= cutoff:
                    idx = i
                    break
            if idx is not None and price_arr[idx] > 0:
                setattr(fv, attr, (price_arr[-1] - price_arr[idx]) / price_arr[idx] * 10000)

        # === MICRO VOLATILITY ===
        kc = list(self._kline_closes[sym])
        if len(kc) >= 5:
            log_rets = [math.log(kc[i] / kc[i - 1]) for i in range(1, len(kc)) if kc[i - 1] > 0]
            if log_rets:
                fv.micro_vol = float(np.std(log_rets[-30:])) * math.sqrt(30)

        kr = list(self._kline_ranges[sym])
        if len(kr) >= 5:
            fv.atr_proxy = float(np.mean(kr[-14:])) / (arr[-1] + 1e-15) * 100

        # === FUNDING ===
        fv.funding_rate = binance_funding
        fv.funding_divergence = binance_funding - bybit_funding

        return fv
