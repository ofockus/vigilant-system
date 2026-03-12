import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.backtester_simple import SimpleTickBacktester, Tick


def test_backtester_replay_basic_profit():
    b = SimpleTickBacktester()
    ticks = [
        Tick(ts=1, price=100, volume=1),
        Tick(ts=2, price=99, volume=1),
        Tick(ts=3, price=100, volume=1),
        Tick(ts=4, price=101, volume=1),
    ]
    result = b.replay(ticks, buy_threshold_pct=-0.5, sell_threshold_pct=0.5)
    assert result.trades >= 1
    assert result.pnl >= 0
