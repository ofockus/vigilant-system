import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.skill_bridge import OpenClawBinanceBridge


def test_openclaw_binance_bridge_execute_path():
    bridge = OpenClawBinanceBridge(score_threshold=70)

    payload = bridge.build_handoff(
        market={
            "primary_symbol": "ETH/USDT",
            "path": "USDT → ETH → BTC → USDT",
            "net_pct": 0.25,
            "net_usd": 0.02,
            "quote_volume_total": 1234567,
            "market_active": True,
            "market_spot": True,
        },
        confluence={"score": 74},
        decision={"allow": True, "warnings": [], "vetoes": []},
    )

    assert payload["binance"]["exchange"] == "binance"
    assert payload["binance"]["symbol"] == "ETHUSDT"
    assert payload["openclaw"]["action"] == "execute"


def test_openclaw_binance_bridge_block_path():
    bridge = OpenClawBinanceBridge(score_threshold=65)

    payload = bridge.build_handoff(
        market={"primary_symbol": "PEPE/USDT", "market_active": True, "market_spot": True},
        confluence={"score": 99},
        decision={"allow": False, "warnings": ["thin_liquidity"], "vetoes": ["rug_risk"]},
    )

    assert payload["openclaw"]["action"] == "block"
    assert payload["openclaw"]["reason"] == "fusion_veto"
    assert payload["openclaw"]["vetoes"] == ["rug_risk"]
