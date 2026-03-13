import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.liquidity_worm import liquidity_worm


def test_liquidity_worm_outputs_all_modules():
    out = liquidity_worm.analyze(
        market={"net_pct": 0.12, "per_leg_spread_bps": {"A": 8, "B": 10}, "quote_volume_total": 3_500_000},
        spoof={"orderbook_imbalance": 0.22, "ghost_walls_detected": 1, "iceberg_detected": False},
        macro={"atr": {"pct": 2.1}, "funding": {"funding_rate": 0.0002}, "open_interest": {"oi_delta": 1.8}, "long_short_ratio": {"ratio": 1.08}},
        regime={"regime": "CONVERGENCE"},
    )
    assert "liquidity_map" in out
    assert "crowding_stress" in out
    assert "sweep_detector" in out
    assert "break_validation" in out
    assert "book_integrity" in out
    assert "probabilities" in out
    assert "acceptance_score" in out["break_validation"]
    assert out["trigger"] in {"wait", "sweep_and_reclaim", "break_hold_retest"}
    assert isinstance(out["labels"], list)


def test_false_break_reversal_label_possible():
    out = liquidity_worm.analyze(
        market={"net_pct": 0.05, "per_leg_spread_bps": {"A": 18}, "quote_volume_total": 5_000_000},
        spoof={"orderbook_imbalance": -0.3, "ghost_walls_detected": 2, "iceberg_detected": False},
        macro={"atr": {"pct": 3.0}, "funding": {"funding_rate": 0.0012}, "open_interest": {"oi_delta": 2.2}, "long_short_ratio": {"ratio": 1.2}},
        regime={"regime": "DIVERGENCE"},
    )
    assert "false_break_sweep_reversal_candidate" in out["labels"] or "squeeze_risk_elevated" in out["labels"]


def test_probabilities_and_regime_fields_present():
    out = liquidity_worm.analyze(
        market={"primary_symbol": "ETHUSDT", "net_pct": 0.3, "per_leg_spread_bps": {"A": 6}, "quote_volume_total": 1_500_000},
        spoof={"orderbook_imbalance": 0.05, "ghost_walls_detected": 0, "iceberg_detected": False},
        macro={"atr": {"pct": 1.4}, "funding": {"funding_rate": 0.0001}, "open_interest": {"oi_delta": 0.4}, "long_short_ratio": {"ratio": 1.01}},
        regime={"regime": "CONVERGENCE"},
    )
    assert 0.0 <= out["probabilities"]["p_sweep"] <= 1.0
    assert 0.0 <= out["probabilities"]["p_trend"] <= 1.0
    assert out["regime"] in {"sweep_reversal", "trend_continuation", "neutral_transition"}
