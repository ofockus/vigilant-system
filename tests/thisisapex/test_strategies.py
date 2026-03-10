import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock
from core.strategies import RiskEngine, FundingCarry, NarrativeSniper

@pytest.fixture
def risk_engine():
    return RiskEngine(initial_capital=430.0)

@pytest.fixture
def mock_exchange():
    exchange = MagicMock()
    exchange.fetch_funding_rate = AsyncMock(return_value={'fundingRate': 0.002})
    exchange.fetch_ticker = AsyncMock(return_value={'quoteVolume': 6_000_000})
    return exchange

def test_risk_engine_drawdown(risk_engine):
    assert risk_engine.can_trade() == True
    
    # Simulate 5% drawdown
    risk_engine.update_capital(430.0 * 0.95)
    assert risk_engine.can_trade() == False

@pytest.mark.asyncio
async def test_funding_carry(mock_exchange, risk_engine):
    carry = FundingCarry(mock_exchange, risk_engine)
    result = await carry.check_opportunity('BTC/USDT')
    assert result == True

@pytest.mark.asyncio
async def test_narrative_sniper(mock_exchange, risk_engine):
    sniper = NarrativeSniper(mock_exchange, risk_engine)
    result = await sniper.check_volume_surge('SOL/USDT')
    assert result == True
