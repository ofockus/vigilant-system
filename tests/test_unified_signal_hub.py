import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.adversarial_shield import AdversarialShieldWorm
from core.fusion_registry import FusionRegistry
from core.unified_signal_hub import UnifiedSignalHub


class DummyConfluence:
    def __init__(self, score: float = 72.0):
        self.score = score
        self.is_valid = True
        self.fake_momentum_flag = False
        self.reversal_risk = 0.10
        self.book_entropy = 0.80
        self.details = {"module_scores": {}}


class DummyExchange:
    async def create_order(self, **kwargs):
        return {"id": "dummy", **kwargs}


def _sample_inputs():
    opp = {
        "id": "abc123",
        "path": "USDT → ETH → BTC → USDT",
        "legs": [
            {"symbol": "ETH/USDT", "side": "buy", "from": "USDT", "to": "ETH"},
            {"symbol": "ETH/BTC", "side": "sell", "from": "ETH", "to": "BTC"},
            {"symbol": "BTC/USDT", "side": "sell", "from": "BTC", "to": "USDT"},
        ],
        "net_pct": 0.22,
        "net_usd": 0.018,
        "capital_needed": 8.0,
    }
    orderbooks = {
        "ETH/USDT": {"bids": [[2500, 10], [2499, 8]], "asks": [[2501, 9], [2502, 8]]},
        "ETH/BTC": {"bids": [[0.05, 20], [0.0499, 15]], "asks": [[0.0501, 18], [0.0502, 14]]},
        "BTC/USDT": {"bids": [[60000, 4], [59990, 3]], "asks": [[60010, 4], [60020, 3]]},
    }
    tickers = {
        "ETH/USDT": {"bid": 2500, "ask": 2501, "quoteVolume": 5_000_000, "percentage": 1.2, "last": 2500},
        "ETH/BTC": {"bid": 0.05, "ask": 0.0501, "quoteVolume": 2_000_000, "percentage": 1.0, "last": 0.05},
        "BTC/USDT": {"bid": 60000, "ask": 60010, "quoteVolume": 10_000_000, "percentage": 1.1, "last": 60000},
    }
    markets = {
        "ETH/USDT": {"active": True, "spot": True},
        "ETH/BTC": {"active": True, "spot": True},
        "BTC/USDT": {"active": True, "spot": True},
    }
    return opp, orderbooks, tickers, markets


@pytest.mark.asyncio
async def test_unified_signal_hub_builds_single_payload():
    hub = UnifiedSignalHub(FusionRegistry(), AdversarialShieldWorm(DummyExchange()))
    opp, orderbooks, tickers, markets = _sample_inputs()

    out = (await hub.run_cycle(
        opportunity=opp,
        confluence_result=DummyConfluence(),
        orderbooks=orderbooks,
        tickers=tickers,
        markets=markets,
    )).to_dict()

    assert "envelope" in out
    assert "decision" in out
    assert "mitigation" in out
    assert "actions" in out
    assert "skill_handoff" in out["envelope"]
    assert isinstance(out["actions"]["ghost_execution_mode"], bool)


@pytest.mark.asyncio
async def test_unified_signal_hub_reports_rotation_and_pause_flags_shape():
    hub = UnifiedSignalHub(FusionRegistry(), AdversarialShieldWorm(DummyExchange()))
    opp, orderbooks, tickers, markets = _sample_inputs()

    out = (await hub.run_cycle(
        opportunity=opp,
        confluence_result=DummyConfluence(score=75.0),
        orderbooks=orderbooks,
        tickers=tickers,
        markets=markets,
    )).to_dict()

    assert "rotate_subaccount_alias" in out["actions"]
    assert "pause_recommended" in out["actions"]
