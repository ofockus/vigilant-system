import sys
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.adversarial_shield import AdversarialShieldWorm


class FakeExchange:
    def __init__(self):
        self.create_order = AsyncMock(return_value={"id": "x1", "status": "open", "params": {"timeInForce": "IOC"}})


@pytest.mark.asyncio
async def test_spoof_detection_from_worm_output():
    shield = AdversarialShieldWorm(FakeExchange())
    out = shield.evaluate_market_state(
        market={"net_pct": 0.05, "quote_volume_total": 3_000_000, "per_leg_spread_bps": {"A": 20}},
        spoof={"orderbook_imbalance": 0.02, "ghost_walls_detected": 0, "iceberg_detected": False},
        macro={"atr": {"pct": 2.0}, "funding": {"funding_rate": 0.0001}, "open_interest": {"oi_delta": 0.2}, "long_short_ratio": {"ratio": 1.0}},
        regime={"regime": "DIVERGENCE"},
    )
    assert "mitigation" in out
    assert isinstance(out["mitigation"]["spoof_detected"], bool)


@pytest.mark.asyncio
async def test_fake_sweep_triggers_ghost_execution():
    ex = FakeExchange()
    shield = AdversarialShieldWorm(ex)

    worm_out = {
        "analysis": {"crowding_stress": {"wvi_instability": 2.2}},
        "mitigation": {"ghost_execution_mode": True, "rotate_subaccount": False, "pause_recommended": False},
    }
    await shield.execute_defensive_order("BTC/USDT", "buy", 0.01, 50000, worm_out)
    _, kwargs = ex.create_order.call_args
    assert kwargs["params"]["timeInForce"] == "IOC"


@pytest.mark.asyncio
async def test_rate_limit_guarded_request_still_retries(monkeypatch):
    shield = AdversarialShieldWorm(FakeExchange())

    state = {"n": 0}

    async def unstable():
        state["n"] += 1
        if state["n"] < 3:
            raise RuntimeError("burst")
        return "ok"

    async def fake_sleep(_v):
        return None

    monkeypatch.setattr("core.adversarial_shield.asyncio.sleep", fake_sleep)
    out = await shield.guarded_request(unstable, max_attempts=3)
    assert out == "ok"
    assert state["n"] == 3
