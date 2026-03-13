import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import asyncio
from unittest.mock import AsyncMock

import pytest

from core.adversarial_shield import AdversarialShield, ShieldConfig


class FakeExchange:
    def __init__(self):
        self.create_order = AsyncMock(
            return_value={"id": "1", "status": "open", "type": "limit", "params": {"timeInForce": "IOC"}}
        )


@pytest.mark.asyncio
async def test_jitter_sleep_range(monkeypatch):
    exchange = FakeExchange()
    shield = AdversarialShield(exchange, ShieldConfig(jitter_range=(0.6, 1.4)))

    monkeypatch.setattr("core.adversarial_shield.random.uniform", lambda a, b: 1.2)
    slept = {"value": 0}

    async def fake_sleep(v):
        slept["value"] = v

    monkeypatch.setattr("core.adversarial_shield.asyncio.sleep", fake_sleep)
    delay = await shield.jitter_sleep(1.0)

    assert delay == 1.2
    assert slept["value"] == 1.2


@pytest.mark.asyncio
async def test_decoy_order_simulation_disabled():
    shield = AdversarialShield(FakeExchange())
    result = await shield.decoy_order_simulation("BTC/USDT")
    assert result["status"] == "disabled"
    assert result["reason"] == "market_manipulation_protection"


@pytest.mark.asyncio
async def test_guarded_request_backoff_then_success(monkeypatch):
    shield = AdversarialShield(FakeExchange())

    state = {"n": 0}

    async def unstable_call():
        state["n"] += 1
        if state["n"] < 3:
            raise RuntimeError("transient")
        return "ok"

    async def fake_sleep(_v):
        return None

    monkeypatch.setattr("core.adversarial_shield.asyncio.sleep", fake_sleep)
    result = await shield.guarded_request(unstable_call, max_attempts=5)
    assert result == "ok"
    assert state["n"] == 3


@pytest.mark.asyncio
async def test_ghost_execute_ioc_calls_exchange():
    exchange = FakeExchange()
    shield = AdversarialShield(exchange)

    out = await shield.ghost_execute_ioc("BTC/USDT", "buy", 0.01, 60000)
    assert out["status"] == "open"
    exchange.create_order.assert_awaited_once()
    _, kwargs = exchange.create_order.call_args
    assert kwargs["params"]["timeInForce"] == "IOC"


def test_behavioral_circuit_breaker_trips():
    shield = AdversarialShield(FakeExchange(), ShieldConfig(breaker_threshold=2, breaker_window_s=120))
    shield.register_exchange_signal("RateLimitExceeded")
    assert shield.should_pause() is False
    shield.register_exchange_signal("DDoSProtection")
    assert shield.should_pause() is True


def test_subaccount_rotation_simulation():
    shield = AdversarialShield(FakeExchange())
    shield.set_subaccounts(["a1", "a2"])
    assert shield.next_subaccount_alias() == "a1"
    assert shield.next_subaccount_alias() == "a2"
    assert shield.next_subaccount_alias() == "a1"
