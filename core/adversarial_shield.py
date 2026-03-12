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

from services.liquidity_worm import LiquidityWormService

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


__all__ = ["AdversarialShield", "ShieldConfig", "AdversarialShieldWorm", "WormShieldConfig", "ccxt_pro"]


@dataclass
class WormShieldConfig:
    spoof_acceptance_threshold: float = 0.45
    sweep_reclaim_threshold: float = 0.55
    psweep_high_threshold: float = 0.68
    wvi_crowding_rotate_threshold: float = 3.0
    wvi_regime_pause_threshold: float = 5.4


class AdversarialShieldWorm(AdversarialShield):
    """Defensive anti-whale adapter powered by LiquidityWormService.

    This class detects hostile microstructure patterns and applies risk mitigation:
    - spoof-risk alarms (wall vanish + weak acceptance)
    - fake sweep alarms (high p_sweep + fast reclaim)
    - adaptive jitter from WVI instability
    - IOC-only defensive execution when sweep-risk is elevated
    - subaccount alias rotation when crowding is extreme (simulation)
    - auto circuit-breaker on hostile regime
    """

    def __init__(
        self,
        exchange: Any,
        config: Optional[ShieldConfig] = None,
        proxy_pool: Optional[Sequence[str]] = None,
        worm_config: Optional[WormShieldConfig] = None,
        worm_service: Optional[LiquidityWormService] = None,
    ) -> None:
        super().__init__(exchange=exchange, config=config, proxy_pool=proxy_pool)
        self.worm_config = worm_config or WormShieldConfig()
        self.worm_service = worm_service or LiquidityWormService()

    def evaluate_market_state(
        self,
        market: Dict[str, Any],
        spoof: Dict[str, Any],
        macro: Dict[str, Any],
        regime: Dict[str, Any],
    ) -> Dict[str, Any]:
        analysis = self.worm_service.analyze(market=market, spoof=spoof, macro=macro, regime=regime)

        brk = analysis.get("break_validation", {})
        swp = analysis.get("sweep_detector", {})
        probs = analysis.get("probabilities", {})
        crowd = analysis.get("crowding_stress", {})
        book = analysis.get("book_integrity", {})

        acceptance = float(brk.get("acceptance_score", 0.0) or 0.0)
        p_sweep = float(probs.get("p_sweep", 0.0) or 0.0)
        reclaim = float(swp.get("reclaim_strength", 0.0) or 0.0)
        wvi_instability = float(crowd.get("wvi_instability", 0.0) or 0.0)
        wvi_crowding = float(crowd.get("wvi_crowding", 0.0) or 0.0)
        wvi = float(crowd.get("wvi", 0.0) or 0.0)

        spoof_detected = bool(book.get("wall_persistence", 0.0) < 0.45 and acceptance <= self.worm_config.spoof_acceptance_threshold)
        fake_sweep_detected = bool(
            p_sweep >= self.worm_config.psweep_high_threshold
            and reclaim >= self.worm_config.sweep_reclaim_threshold
        )
        should_rotate_subaccount = bool(wvi_crowding >= self.worm_config.wvi_crowding_rotate_threshold)
        should_pause = bool(
            analysis.get("regime") == "sweep_reversal"
            and wvi >= self.worm_config.wvi_regime_pause_threshold
        )

        adaptive_jitter = max(0.6, min(1.4, 1.0 + (wvi_instability * 0.1)))

        mitigation = {
            "spoof_detected": spoof_detected,
            "fake_sweep_detected": fake_sweep_detected,
            "ghost_execution_mode": p_sweep >= self.worm_config.psweep_high_threshold,
            "rotate_subaccount": should_rotate_subaccount,
            "pause_recommended": should_pause,
            "adaptive_jitter_factor": round(adaptive_jitter, 4),
        }

        return {
            "analysis": analysis,
            "mitigation": mitigation,
        }

    async def jitter_sleep_from_worm(self, base_delay_s: float, worm_output: Dict[str, Any]) -> float:
        crowd = ((worm_output.get("analysis") or {}).get("crowding_stress") or {})
        instability = float(crowd.get("wvi_instability", 0.0) or 0.0)
        factor = max(0.6, min(1.4, 1.0 + instability * 0.1))
        delay = max(0.0, factor * base_delay_s)
        logger.debug("worm_jitter base={} instability={} factor={} delay={}", base_delay_s, instability, round(factor, 4), round(delay, 4))
        await asyncio.sleep(delay)
        return delay

    async def execute_defensive_order(
        self,
        symbol: str,
        side: str,
        amount: float,
        price: float,
        worm_output: Dict[str, Any],
    ) -> Dict[str, Any]:
        mitigation = worm_output.get("mitigation", {})
        if mitigation.get("ghost_execution_mode"):
            return await self.ghost_execute_ioc(symbol=symbol, side=side, amount=amount, price=price)

        order = await self.exchange.create_order(
            symbol=symbol,
            type="limit",
            side=side,
            amount=amount,
            price=price,
            params={"timeInForce": "GTC"},
        )
        return order

    def maybe_rotate_subaccount(self, worm_output: Dict[str, Any]) -> str | None:
        mitigation = worm_output.get("mitigation", {})
        if mitigation.get("rotate_subaccount"):
            return self.next_subaccount_alias()
        return None

    def maybe_trip_circuit_breaker(self, worm_output: Dict[str, Any]) -> bool:
        mitigation = worm_output.get("mitigation", {})
        if mitigation.get("pause_recommended"):
            self._register_detection_event()
            return True
        return False
