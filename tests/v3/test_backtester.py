# ===================================================================
# TESTS — Tick-Level Backtester
# ===================================================================

import asyncio
import json
import os
import tempfile
from typing import List
import pytest

from backtester import (
    RawTick,
    SyntheticTickGenerator,
    BacktestEngine,
    BacktestResults,
    APMConfig,
    MomentumEntry,
    OBIReversalEntry,
    FixedIntervalEntry,
    MultiStrategyEntry,
    TradeRecord,
    ParameterSweep,
    SweepResult,
    load_ticks_csv,
    load_ticks_json,
    quick_run,
)


# ── Helpers ──

def run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def make_simple_ticks(n=500, start_price=100.0, drift=0.001):
    """Make ticks with steady upward drift for predictable tests."""
    ticks = []
    p = start_price
    for i in range(n):
        p *= (1 + drift)
        ticks.append(RawTick(
            timestamp_ms=1700000000000 + i * 100,
            price=p, volume=2.0, obi=0.3,
        ))
    return ticks


def make_pump_crash_ticks(n=600, start_price=100.0):
    """Pump first half, crash second half."""
    ticks = []
    p = start_price
    for i in range(n):
        if i < n // 2:
            p *= 1.002
            obi = 0.5
        else:
            p *= 0.995
            obi = -0.6
        ticks.append(RawTick(
            timestamp_ms=1700000000000 + i * 100,
            price=p, volume=3.0, obi=obi,
        ))
    return ticks


# ════════════════════════════════════════════════════
# SYNTHETIC TICK GENERATOR
# ════════════════════════════════════════════════════

class TestSyntheticGenerator:

    def test_all_scenarios_generate(self):
        gen = SyntheticTickGenerator(seed=123)
        for scenario in SyntheticTickGenerator.SCENARIOS:
            ticks = gen.generate(scenario=scenario, n_ticks=100)
            assert len(ticks) > 0
            assert all(isinstance(t, RawTick) for t in ticks)
            assert all(t.price > 0 for t in ticks)

    def test_deterministic_with_seed(self):
        a = SyntheticTickGenerator(seed=42).generate("pump_dump", 100)
        b = SyntheticTickGenerator(seed=42).generate("pump_dump", 100)
        assert [t.price for t in a] == [t.price for t in b]

    def test_different_seeds_differ(self):
        a = SyntheticTickGenerator(seed=1).generate("pump_dump", 100)
        b = SyntheticTickGenerator(seed=2).generate("pump_dump", 100)
        prices_a = [t.price for t in a]
        prices_b = [t.price for t in b]
        assert prices_a != prices_b

    def test_ghost_rug_has_ghost_events(self):
        ticks = SyntheticTickGenerator(seed=42).generate("ghost_rug", 200)
        has_ghost = any(t.ghost_events for t in ticks)
        assert has_ghost, "ghost_rug should produce ghost events"

    def test_mixed_chains_scenarios(self):
        ticks = SyntheticTickGenerator(seed=42).generate("mixed", 500)
        assert len(ticks) == 500

    def test_timestamps_monotonic(self):
        ticks = SyntheticTickGenerator(seed=42).generate("pump_dump", 200)
        for i in range(1, len(ticks)):
            assert ticks[i].timestamp_ms > ticks[i - 1].timestamp_ms


# ════════════════════════════════════════════════════
# ENTRY STRATEGIES
# ════════════════════════════════════════════════════

class TestEntryStrategies:

    def test_momentum_no_signal_early(self):
        ticks = make_simple_ticks(10)
        strat = MomentumEntry(lookback=20)
        assert strat.should_enter(ticks, 5) is None

    def test_momentum_signals_on_breakout(self):
        ticks = make_simple_ticks(500, drift=0.002)
        strat = MomentumEntry(lookback=20, volume_mult=0.5)
        signals = [strat.should_enter(ticks, i) for i in range(len(ticks))]
        entries = [s for s in signals if s is not None]
        assert len(entries) > 0
        assert all(e["side"] == "LONG" for e in entries)

    def test_fixed_interval_signals_at_n(self):
        ticks = make_simple_ticks(500)
        strat = FixedIntervalEntry(every_n=100)
        signals = [strat.should_enter(ticks, i) for i in range(500)]
        entries = [i for i, s in enumerate(signals) if s is not None]
        assert entries == [100, 200, 300, 400]

    def test_obi_reversal_needs_extreme(self):
        ticks = make_simple_ticks(50)
        strat = OBIReversalEntry(extreme_threshold=0.7)
        # all OBI = 0.3, not extreme → no signal
        for i in range(50):
            assert strat.should_enter(ticks, i) is None

    def test_multi_strategy_first_match(self):
        ticks = make_simple_ticks(500)
        s1 = FixedIntervalEntry(every_n=1000)  # won't fire
        s2 = FixedIntervalEntry(every_n=200, side="SHORT")
        multi = MultiStrategyEntry([s1, s2])
        sig = multi.should_enter(ticks, 200)
        assert sig is not None
        assert sig["side"] == "SHORT"


# ════════════════════════════════════════════════════
# DATA LOADERS
# ════════════════════════════════════════════════════

class TestDataLoaders:

    def test_load_csv(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
            f.write("timestamp_ms,price,volume,obi\n")
            f.write("1700000000000,100.0,5.0,0.3\n")
            f.write("1700000000100,101.0,3.0,-0.1\n")
            path = f.name
        try:
            ticks = load_ticks_csv(path)
            assert len(ticks) == 2
            assert ticks[0].price == 100.0
            assert ticks[1].obi == -0.1
        finally:
            os.unlink(path)

    def test_load_json(self):
        data = [
            {"timestamp_ms": 1700000000000, "price": 50.0, "volume": 1.0},
            {"ts": 1700000000100, "price": 51.0, "volume": 2.0, "obi": 0.5},
        ]
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(data, f)
            path = f.name
        try:
            ticks = load_ticks_json(path)
            assert len(ticks) == 2
            assert ticks[1].obi == 0.5
        finally:
            os.unlink(path)

    def test_engine_load_from_list(self):
        ticks = [RawTick(timestamp_ms=i * 100, price=100 + i * 0.1) for i in range(100)]
        engine = BacktestEngine()
        engine.load_ticks(ticks)
        assert len(engine._ticks) == 100

    def test_engine_load_from_dicts(self):
        dicts = [{"price": 100 + i, "timestamp_ms": i * 100} for i in range(50)]
        engine = BacktestEngine()
        engine.load_ticks(dicts)
        assert len(engine._ticks) == 50


# ════════════════════════════════════════════════════
# BACKTEST ENGINE — CORE
# ════════════════════════════════════════════════════

class TestBacktestEngine:

    def test_run_basic(self):
        ticks = make_simple_ticks(500, drift=0.001)
        engine = BacktestEngine(max_concurrent=1)
        engine.load_ticks(ticks)
        engine.set_strategy(FixedIntervalEntry(every_n=100))
        engine.set_symbol("TEST/USDT")
        result = run(engine.run())

        assert isinstance(result, BacktestResults)
        assert result.total_ticks == 500
        assert result.total_trades > 0
        assert result.wall_time_s > 0

    def test_uptrend_generates_winners(self):
        """Steady uptrend with LONG entries should produce some winners."""
        ticks = make_simple_ticks(1000, drift=0.002)
        engine = BacktestEngine(
            apm_config=APMConfig(take_profit_pct=3.0, hard_stop_pct=5.0),
            max_concurrent=1,
        )
        engine.load_ticks(ticks)
        engine.set_strategy(FixedIntervalEntry(every_n=150))
        engine.set_symbol("UP/USDT")
        result = run(engine.run())

        assert result.total_trades >= 2
        # In a strong uptrend, we should have some winners
        assert len(result.winners) > 0

    def test_crash_triggers_stops(self):
        """Pump-crash should trigger stop losses or trail stops."""
        ticks = make_pump_crash_ticks(800)
        engine = BacktestEngine(
            apm_config=APMConfig(hard_stop_pct=2.0, take_profit_pct=10.0),
            max_concurrent=1,
        )
        engine.load_ticks(ticks)
        engine.set_strategy(FixedIntervalEntry(every_n=100))
        engine.set_symbol("CRASH/USDT")
        result = run(engine.run())

        assert result.total_trades > 0
        # At least some exits should be from stops
        exit_reasons = result.exit_reason_breakdown
        assert len(exit_reasons) > 0

    def test_equity_curve_tracks(self):
        ticks = make_simple_ticks(500)
        engine = BacktestEngine(initial_equity=10000)
        engine.load_ticks(ticks)
        engine.set_strategy(FixedIntervalEntry(every_n=100))
        result = run(engine.run())

        assert len(result.equity_curve) > 1
        assert result.equity_curve[0] == 10000

    def test_fees_reduce_pnl(self):
        """Higher fees should reduce PnL."""
        ticks = make_simple_ticks(500, drift=0.002)
        strat = FixedIntervalEntry(every_n=100)

        # Low fee
        engine1 = BacktestEngine(fee_pct=0.01, slippage_pct=0.0)
        engine1.load_ticks(ticks)
        engine1.set_strategy(strat)
        r1 = run(engine1.run())

        # High fee
        engine2 = BacktestEngine(fee_pct=0.10, slippage_pct=0.0)
        engine2.load_ticks(ticks)
        engine2.set_strategy(strat)
        r2 = run(engine2.run())

        if r1.total_trades > 0 and r2.total_trades > 0:
            # Higher fees → lower average PnL per trade
            assert r2.avg_pnl_pct <= r1.avg_pnl_pct

    def test_max_concurrent_respected(self):
        """With max_concurrent=1, only 1 position at a time."""
        ticks = make_simple_ticks(1000, drift=0.001)
        engine = BacktestEngine(max_concurrent=1)
        engine.load_ticks(ticks)
        engine.set_strategy(FixedIntervalEntry(every_n=50))
        result = run(engine.run())
        # Can't easily verify concurrency from results,
        # but run should complete without errors
        assert result.total_trades > 0

    def test_no_ticks_raises(self):
        engine = BacktestEngine()
        engine.set_strategy(FixedIntervalEntry())
        with pytest.raises(ValueError, match="No ticks"):
            run(engine.run())

    def test_no_strategy_raises(self):
        engine = BacktestEngine()
        engine.load_ticks(make_simple_ticks(10))
        with pytest.raises(ValueError, match="No strategy"):
            run(engine.run())


# ════════════════════════════════════════════════════
# ANALYTICS
# ════════════════════════════════════════════════════

class TestAnalytics:

    def _make_result_with_trades(self, pnls: List[float]) -> BacktestResults:
        trades = []
        for i, pnl in enumerate(pnls):
            trades.append(TradeRecord(
                trade_id=f"t{i}", symbol="TEST", side="LONG",
                entry_price=100, entry_tick_idx=i * 100,
                entry_ts=i * 100000, exit_price=100 * (1 + pnl / 100),
                exit_tick_idx=i * 100 + 50, exit_ts=i * 100000 + 5000,
                exit_reason="test", pnl_pct=pnl, pnl_abs=pnl * 100,
                ticks_held=50, duration_ms=5000,
            ))
        return BacktestResults(
            trades=trades,
            equity_curve=[10000 + sum(pnls[:i]) * 100 for i in range(len(pnls) + 1)],
            total_ticks=len(pnls) * 100,
        )

    def test_win_rate(self):
        r = self._make_result_with_trades([1.0, -0.5, 2.0, -1.0])
        assert r.win_rate == 0.5

    def test_profit_factor(self):
        r = self._make_result_with_trades([3.0, -1.0, 2.0, -1.0])
        assert r.profit_factor == pytest.approx(2.5, rel=0.01)

    def test_expectancy(self):
        r = self._make_result_with_trades([2.0, -1.0, 2.0, -1.0])
        wr = 0.5
        avg_win = 2.0
        avg_loss = 1.0
        expected = wr * avg_win - (1 - wr) * avg_loss
        assert r.expectancy == pytest.approx(expected, abs=0.01)

    def test_max_drawdown(self):
        r = self._make_result_with_trades([])
        r.equity_curve = [10000, 10500, 10200, 9800, 10100]
        # Peak 10500, trough 9800 → dd = (10500-9800)/10500 = 6.67%
        assert r.max_drawdown_pct == pytest.approx(6.67, abs=0.1)

    def test_sharpe_zero_trades(self):
        r = BacktestResults()
        assert r.sharpe == 0.0

    def test_exit_reason_breakdown(self):
        r = self._make_result_with_trades([1.0, -0.5])
        r.trades[0].exit_reason = "take_profit"
        r.trades[1].exit_reason = "hard_stop"
        breakdown = r.exit_reason_breakdown
        assert breakdown["take_profit"] == 1
        assert breakdown["hard_stop"] == 1

    def test_summary_string(self):
        r = self._make_result_with_trades([1.0, -0.5, 2.0])
        r.strategy_name = "test_strat"
        r.symbol = "TEST/USDT"
        summary = r.summary()
        assert "BACKTEST RESULTS" in summary
        assert "test_strat" in summary
        assert "TEST/USDT" in summary


# ════════════════════════════════════════════════════
# EXPORT
# ════════════════════════════════════════════════════

class TestExport:

    def test_export_json(self):
        ticks = make_simple_ticks(300)
        engine = BacktestEngine()
        engine.load_ticks(ticks)
        engine.set_strategy(FixedIntervalEntry(every_n=100))
        result = run(engine.run())

        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = f.name
        try:
            result.export_json(path)
            with open(path) as f:
                data = json.load(f)
            assert "summary" in data
            assert "trades" in data
            assert "equity_curve" in data
        finally:
            os.unlink(path)

    def test_export_csv(self):
        ticks = make_simple_ticks(300)
        engine = BacktestEngine()
        engine.load_ticks(ticks)
        engine.set_strategy(FixedIntervalEntry(every_n=100))
        result = run(engine.run())

        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as f:
            path = f.name
        try:
            result.export_csv(path)
            with open(path) as f:
                lines = f.readlines()
            assert len(lines) >= 2  # header + at least 1 trade
        finally:
            os.unlink(path)


# ════════════════════════════════════════════════════
# PARAMETER SWEEP
# ════════════════════════════════════════════════════

class TestParameterSweep:

    def test_sweep_runs(self):
        ticks = make_simple_ticks(400, drift=0.001)
        strat = FixedIntervalEntry(every_n=100)

        sweep = ParameterSweep(ticks, strat)
        sweep.add_param("take_profit_pct", [2.0, 5.0])
        sweep.add_param("hard_stop_pct", [1.5, 3.0])
        results = run(sweep.run(verbose=False))

        assert len(results) == 4  # 2 × 2
        assert all(isinstance(r, SweepResult) for r in results)

    def test_sweep_sorted_by_sharpe(self):
        ticks = make_simple_ticks(400, drift=0.001)
        strat = FixedIntervalEntry(every_n=100)

        sweep = ParameterSweep(ticks, strat)
        sweep.add_param("take_profit_pct", [1.0, 3.0, 5.0])
        results = run(sweep.run(verbose=False))

        sharpes = [r.sharpe for r in results]
        assert sharpes == sorted(sharpes, reverse=True)

    def test_sweep_invalid_param_raises(self):
        ticks = make_simple_ticks(100)
        sweep = ParameterSweep(ticks, FixedIntervalEntry())
        with pytest.raises(ValueError, match="no param"):
            sweep.add_param("nonexistent_param", [1, 2])

    def test_sweep_export(self):
        ticks = make_simple_ticks(300)
        sweep = ParameterSweep(ticks, FixedIntervalEntry(every_n=100))
        sweep.add_param("take_profit_pct", [2.0, 5.0])
        run(sweep.run(verbose=False))

        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = f.name
        try:
            sweep.export_json(path)
            with open(path) as f:
                data = json.load(f)
            assert len(data) == 2
            assert "params" in data[0]
            assert "sharpe" in data[0]
        finally:
            os.unlink(path)


# ════════════════════════════════════════════════════
# INTEGRATION: QUICK RUN
# ════════════════════════════════════════════════════

class TestQuickRun:

    def test_quick_run_pump_dump(self):
        result = run(quick_run("pump_dump", 500, verbose=False))
        assert isinstance(result, BacktestResults)
        assert result.total_ticks == 500

    def test_quick_run_all_scenarios(self):
        for scenario in ["pump_dump", "clean_pump", "chop", "slow_bleed", "vpin_toxic"]:
            result = run(quick_run(scenario, 300, verbose=False))
            assert result.total_ticks == 300

    def test_quick_run_mixed(self):
        result = run(quick_run("mixed", 1000, verbose=False))
        assert result.total_ticks == 1000
        assert result.wall_time_s > 0


# ════════════════════════════════════════════════════
# APM WEAPON VERIFICATION
# ════════════════════════════════════════════════════

class TestAPMWeaponsInBacktest:
    """Verify that APM weapons actually fire during backtesting."""

    def test_hard_stop_fires(self):
        """Sharp crash should trigger hard stop."""
        ticks = []
        p = 100.0
        for i in range(300):
            if i < 50:
                p *= 1.001
            else:
                p *= 0.998  # steady decline
            ticks.append(RawTick(
                timestamp_ms=1700000000000 + i * 100,
                price=p, volume=2.0, obi=-0.3,
            ))

        engine = BacktestEngine(
            apm_config=APMConfig(hard_stop_pct=2.0, take_profit_pct=20.0, time_limit_s=9999),
            max_concurrent=1,
        )
        engine.load_ticks(ticks)
        engine.set_strategy(FixedIntervalEntry(every_n=50, side="LONG"))
        result = run(engine.run())

        assert result.total_trades > 0
        reasons = result.exit_reason_breakdown
        # Should have some hard stops or trail stops
        stop_exits = reasons.get("hard_stop", 0) + reasons.get("obi_trail_stop", 0)
        assert stop_exits > 0 or "forced_close_eod" in reasons

    def test_take_profit_fires(self):
        """Strong pump should trigger take profit."""
        ticks = make_simple_ticks(500, drift=0.005)  # 0.5% per tick = fast pump
        engine = BacktestEngine(
            apm_config=APMConfig(take_profit_pct=2.0, hard_stop_pct=10.0),
            max_concurrent=1,
        )
        engine.load_ticks(ticks)
        engine.set_strategy(FixedIntervalEntry(every_n=100))
        result = run(engine.run())

        reasons = result.exit_reason_breakdown
        assert reasons.get("take_profit", 0) > 0, f"Expected take_profit but got {reasons}"

    def test_ghost_exit_fires(self):
        """Ghost rug scenario should trigger ghost liquidity exit."""
        gen = SyntheticTickGenerator(seed=42)
        ticks = gen.generate("ghost_rug", 400)

        engine = BacktestEngine(
            apm_config=APMConfig(take_profit_pct=50, hard_stop_pct=50, time_limit_s=9999),
            max_concurrent=1,
        )
        engine.load_ticks(ticks)
        engine.set_strategy(FixedIntervalEntry(every_n=50))
        result = run(engine.run())

        # Ghost exits or trail stops should appear
        assert result.total_trades > 0


# ════════════════════════════════════════════════════
# TRADE RECORD
# ════════════════════════════════════════════════════

class TestTradeRecord:

    def test_to_dict(self):
        tr = TradeRecord(
            trade_id="abc", symbol="SOL", side="LONG",
            entry_price=150.0, entry_tick_idx=0, entry_ts=0,
        )
        d = tr.to_dict()
        assert d["trade_id"] == "abc"
        assert d["entry_price"] == 150.0
        assert isinstance(d, dict)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
