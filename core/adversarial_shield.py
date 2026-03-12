"""Operational resilience shield for Binance execution.

Security/compliance note:
- This module is intentionally designed for defensive reliability.
- It does NOT implement market manipulation techniques (e.g., spoofing) or
  exchange detection bypass behavior.
"""
from __future__ import annotations

import asyncio
import os
import random
import time
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Dict, Iterable, List, Optional, Sequence, Tuple

from dotenv import load_dotenv
from loguru import logger

try:
    # Preferred path requested by user.
    import ccxt.pro as ccxt_pro
except Exception:  # pragma: no cover - fallback for local CI/dev without ccxt.pro
    import ccxt.async_support as ccxt_pro


load_dotenv()


@dataclass
class ShieldConfig:
    max_requests_per_min: int = int(os.getenv("MAX_REQUESTS_PER_MIN", "120"))
    jitter_range: Tuple[float, float] = tuple(
        float(v.strip()) for v in os.getenv("JITTER_RANGE", "0.6,1.2").split(",", 1)
    )  # type: ignore[assignment]
    breaker_window_s: int = int(os.getenv("BREAKER_WINDOW_S", "60"))
    breaker_threshold: int = int(os.getenv("BREAKER_THRESHOLD", "4"))


class AdversarialShield:
    """Resilience layer for exchange operations using async ccxt clients."""

    def __init__(
        self,
        exchange: Any,
        config: Optional[ShieldConfig] = None,
        proxy_pool: Optional[Sequence[str]] = None,
    ) -> None:
        self.exchange = exchange
        self.config = config or ShieldConfig()
        self.proxy_pool = list(proxy_pool or ["direct", "proxy-a", "proxy-b"])

        self._request_timestamps: List[float] = []
        self._detection_events: List[float] = []
        self._subaccounts: List[str] = ["primary"]
        self._sub_idx: int = 0

        logger.debug("AdversarialShield initialized with config={}", self.config)

    # 1) Adaptive jitter
    async def jitter_sleep(self, base_delay_s: float) -> float:
        factor = random.uniform(*self.config.jitter_range)
        delay = max(0.0, factor * base_delay_s)
        logger.debug(
            "jitter_sleep | base={} factor={} delay={}",
            base_delay_s,
            round(factor, 4),
            round(delay, 4),
        )
        await asyncio.sleep(delay)
        return delay

    # 2) Decoy orders (disabled by design)
    async def decoy_order_simulation(self, symbol: str) -> Dict[str, Any]:
        """No-op placeholder.

        Intentionally disabled to avoid manipulative behavior and policy violations.
        """
        logger.warning(
            "decoy_order_simulation called for {}. Disabled: compliance protection active.",
            symbol,
        )
        return {"status": "disabled", "reason": "market_manipulation_protection", "symbol": symbol}

    # 3) Rate-limit resilience with backoff + proxy rotation simulation
    async def guarded_request(
        self,
        request_fn: Callable[[], Awaitable[Any]],
        *,
        max_attempts: int = 3,
        base_backoff_s: float = 0.25,
    ) -> Any:
        self._enforce_local_budget()

        last_exc: Optional[Exception] = None
        for attempt in range(1, max_attempts + 1):
            proxy = self.proxy_pool[(attempt - 1) % len(self.proxy_pool)]
            logger.debug("guarded_request attempt={} proxy={}", attempt, proxy)
            try:
                result = await request_fn()
                self._request_timestamps.append(time.time())
                return result
            except Exception as exc:
                last_exc = exc
                backoff = (2 ** (attempt - 1)) * base_backoff_s * random.uniform(0.7, 1.3)
                logger.debug(
                    "guarded_request retry | attempt={} error={} backoff={}",
                    attempt,
                    type(exc).__name__,
                    round(backoff, 4),
                )
                await asyncio.sleep(backoff)

        self._register_detection_event()
        raise RuntimeError("guarded_request exhausted retries") from last_exc

    # 4) IOC execution path (legitimate immediate-or-cancel)
    async def ghost_execute_ioc(
        self,
        symbol: str,
        side: str,
        amount: float,
        price: float,
    ) -> Dict[str, Any]:
        logger.debug("ghost_execute_ioc symbol={} side={} amount={} price={}", symbol, side, amount, price)
        params = {"timeInForce": "IOC"}
        order = await self.exchange.create_order(
            symbol=symbol,
            type="limit",
            side=side,
            amount=amount,
            price=price,
            params=params,
        )
        return order

    # 5) Behavioral circuit breaker
    def should_pause(self) -> bool:
        now = time.time()
        self._detection_events = [t for t in self._detection_events if now - t <= self.config.breaker_window_s]
        tripped = len(self._detection_events) >= self.config.breaker_threshold
        logger.debug(
            "should_pause events={} threshold={} tripped={}",
            len(self._detection_events),
            self.config.breaker_threshold,
            tripped,
        )
        return tripped

    async def pause_if_tripped(self, cooldown_s: float = 30.0) -> bool:
        if not self.should_pause():
            return False
        logger.warning("Circuit breaker tripped. Cooling down for {}s", cooldown_s)
        await asyncio.sleep(cooldown_s)
        return True

    def register_exchange_signal(self, signal: str) -> None:
        monitored = {"DDoSProtection", "RateLimitExceeded", "InvalidNonce", "AuthenticationError"}
        if signal in monitored:
            self._register_detection_event()
            logger.debug("register_exchange_signal signal={} total_events={}", signal, len(self._detection_events))

    # 6) Subaccount rotation simulation
    def set_subaccounts(self, aliases: Iterable[str]) -> None:
        values = [a for a in aliases if a]
        self._subaccounts = values or ["primary"]
        self._sub_idx = 0

    def next_subaccount_alias(self) -> str:
        alias = self._subaccounts[self._sub_idx % len(self._subaccounts)]
        self._sub_idx += 1
        logger.debug("next_subaccount_alias={}", alias)
        return alias

    # NOTE: real implementation should inject key/secret pairs from a secure vault
    # and instantiate dedicated ccxt.pro exchange clients per subaccount.

    def _enforce_local_budget(self) -> None:
        now = time.time()
        self._request_timestamps = [t for t in self._request_timestamps if now - t <= 60]
        if len(self._request_timestamps) >= self.config.max_requests_per_min:
            self._register_detection_event()
            raise RuntimeError("local_request_budget_exceeded")

    def _register_detection_event(self) -> None:
        self._detection_events.append(time.time())


__all__ = ["AdversarialShield", "ShieldConfig", "ccxt_pro"]
