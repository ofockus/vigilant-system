import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.fusion_registry import fusion_registry


class DummyConfluence:
    def __init__(self, score: float = 72.0):
        self.score = score
        self.is_valid = True
        self.fake_momentum_flag = False
        self.reversal_risk = 0.10
        self.book_entropy = 0.80
        self.details = {"module_scores": {}}


import pytest


@pytest.mark.asyncio
async def test_fusion_registry_allows_clean_setup():
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
        "ETH/USDT": {"bids": [[2500, 10], [2499, 8], [2498, 7]], "asks": [[2501, 9], [2502, 8], [2503, 7]]},
        "ETH/BTC": {"bids": [[0.05, 20], [0.0499, 15], [0.0498, 11]], "asks": [[0.0501, 18], [0.0502, 14], [0.0503, 10]]},
        "BTC/USDT": {"bids": [[60000, 4], [59990, 3], [59980, 2]], "asks": [[60010, 4], [60020, 3], [60030, 2]]},
    }
    tickers = {
        "ETH/USDT": {"bid": 2500, "ask": 2501, "quoteVolume": 5_000_000, "percentage": 1.2, "last": 2500, "high": 2550, "low": 2450},
        "ETH/BTC": {"bid": 0.05, "ask": 0.0501, "quoteVolume": 2_000_000, "percentage": 1.0, "last": 0.05, "high": 0.051, "low": 0.049},
        "BTC/USDT": {"bid": 60000, "ask": 60010, "quoteVolume": 10_000_000, "percentage": 1.1, "last": 60000, "high": 60500, "low": 59500},
    }
    markets = {
        "ETH/USDT": {"active": True, "spot": True},
        "ETH/BTC": {"active": True, "spot": True},
        "BTC/USDT": {"active": True, "spot": True},
    }

    env = await fusion_registry.evaluate_opportunity(
        opportunity=opp,
        confluence_result=DummyConfluence(),
        orderbooks=orderbooks,
        tickers=tickers,
        markets=markets,
    )
    assert env.decision["allow"] is True
    assert env.decision["final_score"] >= 68
    assert env.skill_handoff["binance"]["exchange"] == "binance"
    assert env.skill_handoff["openclaw"]["action"] in {"execute", "watch"}
    assert "liquidity_map" in env.liquidity
    assert "true_break_prob" in env.liquidity["break_validation"]


@pytest.mark.asyncio
async def test_fusion_registry_blocks_thin_suspicious_setup():
    opp = {
        "id": "bad001",
        "path": "USDT → PEPEUP → BTC → USDT",
        "legs": [
            {"symbol": "PEPEUP/USDT", "side": "buy", "from": "USDT", "to": "PEPEUP"},
            {"symbol": "PEPEUP/BTC", "side": "sell", "from": "PEPEUP", "to": "BTC"},
            {"symbol": "BTC/USDT", "side": "sell", "from": "BTC", "to": "USDT"},
        ],
        "net_pct": 0.35,
        "net_usd": 0.028,
        "capital_needed": 8.0,
    }
    orderbooks = {
        "PEPEUP/USDT": {"bids": [[1.0, 1000], [0.99, 10], [0.98, 10]], "asks": [[1.05, 2], [1.06, 2], [1.07, 2]]},
        "PEPEUP/BTC": {"bids": [[0.00001, 500], [0.0000099, 10], [0.0000098, 10]], "asks": [[0.000011, 1], [0.000012, 1], [0.000013, 1]]},
        "BTC/USDT": {"bids": [[60000, 4], [59990, 3], [59980, 2]], "asks": [[60010, 4], [60020, 3], [60030, 2]]},
    }
    tickers = {
        "PEPEUP/USDT": {"bid": 1.0, "ask": 1.05, "quoteVolume": 25_000, "percentage": 9.0, "last": 1.02, "high": 1.20, "low": 0.80},
        "PEPEUP/BTC": {"bid": 0.00001, "ask": 0.000011, "quoteVolume": 8_000, "percentage": 10.0, "last": 0.0000105, "high": 0.000012, "low": 0.000008},
        "BTC/USDT": {"bid": 60000, "ask": 60010, "quoteVolume": 10_000_000, "percentage": 1.1, "last": 60000, "high": 60500, "low": 59500},
    }
    markets = {
        "PEPEUP/USDT": {"active": True, "spot": True},
        "PEPEUP/BTC": {"active": True, "spot": True},
        "BTC/USDT": {"active": True, "spot": True},
    }

    env = await fusion_registry.evaluate_opportunity(
        opportunity=opp,
        confluence_result=DummyConfluence(score=74.0),
        orderbooks=orderbooks,
        tickers=tickers,
        markets=markets,
    )
    assert env.decision["allow"] is False
    assert env.decision["vetoes"]
    assert env.skill_handoff["openclaw"]["action"] == "block"
    assert "book_integrity" in env.liquidity
