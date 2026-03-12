"""Small strategy primitives used by legacy tests and examples."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class RiskEngine:
    initial_capital: float
    max_drawdown_pct: float = 5.0

    def __post_init__(self) -> None:
        self.current_capital = float(self.initial_capital)

    def update_capital(self, capital: float) -> None:
        self.current_capital = float(capital)

    def can_trade(self) -> bool:
        floor = self.initial_capital * (1.0 - self.max_drawdown_pct / 100.0)
        return self.current_capital > floor


class FundingCarry:
    def __init__(self, exchange, risk_engine: RiskEngine, min_funding_rate: float = 0.001) -> None:
        self.exchange = exchange
        self.risk_engine = risk_engine
        self.min_funding_rate = min_funding_rate

    async def check_opportunity(self, symbol: str) -> bool:
        if not self.risk_engine.can_trade():
            return False
        snap = await self.exchange.fetch_funding_rate(symbol)
        funding_rate = float((snap or {}).get("fundingRate", 0.0) or 0.0)
        return funding_rate >= self.min_funding_rate


class NarrativeSniper:
    def __init__(self, exchange, risk_engine: RiskEngine, min_volume: float = 5_000_000) -> None:
        self.exchange = exchange
        self.risk_engine = risk_engine
        self.min_volume = min_volume

    async def check_volume_surge(self, symbol: str) -> bool:
        if not self.risk_engine.can_trade():
            return False
        ticker = await self.exchange.fetch_ticker(symbol)
        volume = float((ticker or {}).get("quoteVolume", 0.0) or 0.0)
        return volume >= self.min_volume
