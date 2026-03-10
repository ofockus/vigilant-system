import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.chart_confluence_engine import chart_confluence
from core.confluence_engine import confluence


def _make_bullish_frame(rows: int = 96) -> pd.DataFrame:
    np.random.seed(11)
    base = 100.0
    rets = np.random.normal(0.0010, 0.0025, rows)
    close = base * np.exp(np.cumsum(rets))
    open_ = np.roll(close, 1)
    open_[0] = close[0] * 0.998
    high = np.maximum(open_, close) * (1 + np.random.uniform(0.001, 0.004, rows))
    low = np.minimum(open_, close) * (1 - np.random.uniform(0.001, 0.004, rows))
    volume = np.random.uniform(1000, 3000, rows)

    impulse_idx = rows - 8
    close[impulse_idx] *= 1.018
    high[impulse_idx] = max(high[impulse_idx], close[impulse_idx] * 1.003)
    volume[impulse_idx] *= 2.4

    return pd.DataFrame({
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
    })


def test_chart_confluence_engine_returns_decision():
    df = _make_bullish_frame()
    assessment = chart_confluence.assess(df)
    assert assessment.decision.final_score >= 0
    assert assessment.decision.trend in {"bullish", "bearish", "neutral"}
    assert assessment.levels["local_support"] is not None


def test_local_confluence_blends_chart_signal_when_candles_exist():
    df = _make_bullish_frame()
    triangle = {
        "legs": [
            {"symbol": "ETH/USDT", "side": "buy"},
            {"symbol": "ETH/BTC", "side": "sell"},
            {"symbol": "BTC/USDT", "side": "sell"},
        ],
        "net_profit_pct": 0.21,
    }
    orderbooks = {
        "ETH/USDT": {"bids": [[2500, 10], [2499, 7], [2498, 5]], "asks": [[2501, 9], [2502, 8], [2503, 6]]},
        "ETH/BTC": {"bids": [[0.05, 20], [0.0499, 15], [0.0498, 11]], "asks": [[0.0501, 18], [0.0502, 14], [0.0503, 10]]},
        "BTC/USDT": {"bids": [[60000, 4], [59990, 3], [59980, 2]], "asks": [[60010, 4], [60020, 3], [60030, 2]]},
    }
    tickers = {
        "ETH/USDT": {"bid": 2500, "ask": 2501, "quoteVolume": 5_000_000, "percentage": 1.2, "last": 2500, "high": 2550, "low": 2450},
        "ETH/BTC": {"bid": 0.05, "ask": 0.0501, "quoteVolume": 2_000_000, "percentage": 1.0, "last": 0.05, "high": 0.051, "low": 0.049},
        "BTC/USDT": {"bid": 60000, "ask": 60010, "quoteVolume": 10_000_000, "percentage": 1.1, "last": 60000, "high": 60500, "low": 59500},
    }

    result = confluence.analyze(
        triangle,
        orderbooks,
        tickers,
        candles_by_symbol={"ETH/USDT": df},
    )
    assert result.details["chart"] is not None
    assert result.chart_score is not None
    assert result.chart_allow in {True, False}
