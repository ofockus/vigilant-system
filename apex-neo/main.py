"""
Apex NEO — Main Orchestrator.

Single-process entry point that boots all subsystems, runs the signal loop,
and handles graceful shutdown. Connects to Binance, processes market data
through 9 signal layers, manages positions, and broadcasts to dashboard.

Usage:
    python3 main.py --mode observe
    python3 main.py --mode paper
    python3 main.py --mode live   (prompts for confirmation)
"""

from __future__ import annotations

import argparse
import asyncio
import signal
import sys
import time
from typing import Any

from loguru import logger

from config import Config
from dashboard.server import dashboard_state, run_dashboard
from engine.calibrator import Calibrator
from engine.cross_intel import CrossIntelEngine
from engine.drift import DriftEngine
from engine.flow import OrderFlowEngine
from engine.physics import PhysicsEngine
from engine.predictor import Predictor
from engine.shield import AdversarialShield
from engine.toxicity import ToxicityEngine
from engine.whale import WhaleClassifier
from telegram.bot import TelegramBot
from trading.connector import BinanceConnector
from trading.executor import Executor
from trading.regime import RegimeGate
from trading.risk import RiskManager
from utils.journal import StateStore, TradeJournal
from utils.logging import setup_logging


class ApexNeo:
    """Main orchestrator — boots, runs signal loop, shuts down."""

    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        self._running = False
        self._start_time = time.time()

        # --- Subsystems ---
        self.connector = BinanceConnector(
            api_key=cfg.binance_api_key,
            api_secret=cfg.binance_api_secret,
            testnet=cfg.testnet,
            market_type=cfg.market_type,
        )

        self.predictor = Predictor(
            ou_window=cfg.ou_window,
            momentum_window=cfg.momentum_window,
        )
        self.physics = PhysicsEngine()
        self.toxicity = ToxicityEngine(
            n_buckets=cfg.vpin_buckets,
            vpin_critical=cfg.vpin_critical,
        )
        self.shield = AdversarialShield()
        self.cross_intel = CrossIntelEngine(enabled=cfg.bybit_enabled)
        self.drift = DriftEngine(delta=cfg.adwin_delta)
        self.calibrator = Calibrator()
        self.flow = OrderFlowEngine()
        self.whale = WhaleClassifier(multiplier=cfg.whale_multiplier)

        self.regime = RegimeGate(
            threshold=cfg.regime_threshold,
            block_timeout_s=cfg.regime_block_timeout_s,
        )
        self.risk = RiskManager(
            capital=cfg.capital,
            max_drawdown_pct=cfg.max_drawdown_pct,
            pause_duration_s=cfg.pause_duration_s,
            equity_floor_pct=cfg.equity_floor_pct,
        )
        self.executor = Executor(
            mode=cfg.mode,
            connector=self.connector,
            capital=cfg.capital,
            max_position_pct=cfg.max_position_pct,
            leverage=cfg.leverage,
            min_hold_s=cfg.min_hold_s,
            stop_loss_pct=cfg.stop_loss_pct,
            trail_base_pct=cfg.trail_base_pct,
            trail_max_pct=cfg.trail_max_pct,
            decel_threshold=cfg.decel_threshold,
            vpin_critical=cfg.vpin_critical,
            cooldown_s=cfg.cooldown_s,
        )

        self.journal = TradeJournal(cfg.journal_path)
        self.state_store = StateStore(cfg.state_path)
        self.telegram = TelegramBot(cfg.telegram_token, cfg.telegram_chat_id)

        # Regime tracking for notifications
        self._prev_regime_blocked = False
        self._daily_summary_sent = 0.0

    async def start(self) -> None:
        """Boot all subsystems and start the main loop."""
        logger.info("=" * 60)
        logger.info("APEX NEO starting | mode={} testnet={}", self.cfg.mode, self.cfg.testnet)
        logger.info("=" * 60)

        # Load persisted state
        saved = self.state_store.load()
        if saved:
            self.calibrator.load_state(saved)
            logger.info("Loaded calibration state from disk")

        # Connect to exchange
        await self.connector.start()

        if self.cfg.market_type == "future":
            await self.connector.set_leverage(self.cfg.primary_pair, self.cfg.leverage)

        # Setup Telegram callbacks
        self.telegram.set_callbacks(
            status_fn=self._get_full_status,
            pnl_fn=lambda: {
                "session_pnl": self.executor.session_pnl,
                "trade_count": self.executor.trade_count,
                **self.risk.get_status(),
            },
            equity_fn=lambda: self.risk.state.current_equity,
            kill_fn=self._request_stop,
            resume_fn=lambda: logger.info("Resume requested via Telegram"),
        )

        await self.telegram.send(
            f"<b>Apex NEO started</b>\n"
            f"Mode: {self.cfg.mode}\n"
            f"Testnet: {self.cfg.testnet}\n"
            f"Capital: ${self.cfg.capital}"
        )

        self._running = True

        # Launch concurrent tasks
        tasks = [
            asyncio.create_task(self._signal_loop(), name="signal_loop"),
            asyncio.create_task(self._trade_stream(), name="trade_stream"),
            asyncio.create_task(self._book_stream(), name="book_stream"),
            asyncio.create_task(self._dashboard_broadcaster(), name="dashboard_bc"),
            asyncio.create_task(run_dashboard(self.cfg.dashboard_host, self.cfg.dashboard_port), name="dashboard"),
            asyncio.create_task(self.telegram.poll_commands(), name="telegram"),
            asyncio.create_task(self._cross_intel_loop(), name="cross_intel"),
            asyncio.create_task(self._daily_summary_loop(), name="daily_summary"),
        ]

        logger.info("All systems online. Entering main loop.")

        try:
            await asyncio.gather(*tasks)
        except asyncio.CancelledError:
            logger.info("Main loop cancelled")
        finally:
            await self.shutdown()

    async def shutdown(self) -> None:
        """Graceful shutdown."""
        logger.info("Shutting down...")
        self._running = False

        # Save calibration state
        self.state_store.save(self.calibrator.save_state())

        await self.telegram.send("<b>Apex NEO stopped</b>")
        await self.telegram.close()
        await self.cross_intel.close()
        await self.connector.stop()
        logger.info("Shutdown complete")

    def _request_stop(self) -> None:
        self._running = False

    # ─── Data Streams ────────────────────────────────────────

    async def _trade_stream(self) -> None:
        """Process incoming trades for flow, toxicity, and whale detection."""
        logger.info("Trade stream starting for {}", self.cfg.primary_pair)
        try:
            async for trade in self.connector.watch_trades(self.cfg.primary_pair):
                if not self._running:
                    break

                # L3: Toxicity
                tox = self.toxicity.update_trade(
                    trade.price, trade.amount, trade.is_buy, trade.timestamp
                )

                # L8: Order flow
                flow = self.flow.update(
                    trade.price, trade.amount, trade.is_buy, trade.timestamp
                )

                # L9: Whale detection
                shield_sig = self.shield.update([], [], trade.timestamp)  # book update happens in _book_stream
                whale = self.whale.update(
                    trade.price, trade.amount, trade.is_buy, trade.timestamp,
                    ghost_count=shield_sig.ghost_count,
                    spoof_score=shield_sig.spoof_score,
                )

                if whale.whale_detected and whale.latest_event:
                    logger.info(
                        "WHALE {} | vol={:.4f} | class={}",
                        "BUY" if trade.is_buy else "SELL",
                        trade.amount,
                        whale.latest_event.classification,
                    )
                    await self.telegram.notify_whale({
                        "classification": whale.latest_event.classification,
                        "volume": trade.amount,
                        "is_buy": trade.is_buy,
                    })

        except asyncio.CancelledError:
            return
        except Exception as e:
            logger.error("Trade stream error: {}", e)

    async def _book_stream(self) -> None:
        """Process orderbook updates for shield (ghost walls, spoofing)."""
        logger.info("Orderbook stream starting for {}", self.cfg.primary_pair)
        try:
            async for book in self.connector.watch_orderbook(self.cfg.primary_pair):
                if not self._running:
                    break
                self.shield.update(book.bids, book.asks, book.timestamp)
        except asyncio.CancelledError:
            return
        except Exception as e:
            logger.error("Book stream error: {}", e)

    # ─── Main Signal Loop ────────────────────────────────────

    async def _signal_loop(self) -> None:
        """Core tick loop: fetch price, run signals, check entry/exit."""
        logger.info("Signal loop starting | interval={}s", self.cfg.tick_interval_s)
        await asyncio.sleep(2)  # let streams initialize

        while self._running:
            try:
                tick = await self.connector.fetch_ticker(self.cfg.primary_pair)
                price = tick.price
                if price <= 0:
                    await asyncio.sleep(self.cfg.tick_interval_s)
                    continue

                now = time.time()

                # L1: Predictor
                pred = self.predictor.update(price)

                # L2: Physics
                phys = self.physics.update(price, tick.volume_24h)

                # L6: Drift
                drift = self.drift.update(price)

                # L7: Calibrator (price tracking)
                self.calibrator.update_price(price)

                # Get latest from async engines (updated via streams)
                tox_signal = self.toxicity.update_trade(price, 0.001, True, now)
                flow_signal = self.flow.update(price, 0.001, True, now)

                # L5: Cross-intel (fetched periodically)
                funding = await self.cross_intel.fetch()

                # Get latest shield state
                bid_levels = self.shield.ghost_tracker.prev_levels.get("bid", {})
                ask_levels = self.shield.ghost_tracker.prev_levels.get("ask", {})
                bid_list = [[p, s] for p, s in bid_levels.items()] if isinstance(bid_levels, dict) else []
                ask_list = [[p, s] for p, s in ask_levels.items()] if isinstance(ask_levels, dict) else []

                shield_sig = ShieldSnapshot(
                    ghost_count=len(self.shield.ghost_tracker.ghost_events),
                    spoof_score=self.shield.spoof_classifier.classify(bid_list, ask_list),
                    safe=True,
                )

                # Regime gate update
                regime = self.regime.update(
                    vpin=tox_signal.vpin,
                    ghost_count=shield_sig.ghost_count,
                    liq_intensity=tox_signal.liq_intensity,
                    spoof_score=shield_sig.spoof_score,
                    drift_detected=drift.drift_detected,
                    drift_magnitude=drift.drift_magnitude,
                    funding_divergence=funding.divergence,
                    flow_intensity=flow_signal.intensity,
                )

                # Notify on regime changes
                if regime.blocked != self._prev_regime_blocked:
                    self._prev_regime_blocked = regime.blocked
                    await self.telegram.notify_regime_change(
                        regime.blocked, regime.block_reason, regime.score
                    )

                # Risk check
                risk_ok, risk_reason = self.risk.check_allowed()

                # Composite direction: weighted blend of all directional signals
                whale_dir = 0.0
                if self.whale.whale_events:
                    last_whale = self.whale.whale_events[-1]
                    whale_dir = last_whale.confidence * (1.0 if last_whale.is_buy else -1.0)
                    if last_whale.classification == "spoof_fade":
                        whale_dir *= -1.0

                drift_component = drift.mean_shift * 10 if drift.drift_detected else 0.0

                direction = (
                    pred.direction * 0.25
                    + phys.direction * 0.25
                    + flow_signal.imbalance * 0.15
                    + funding.direction_bias * 0.10
                    + whale_dir * 0.10
                    + drift_component * 0.05
                )
                direction = max(-1.0, min(1.0, direction))

                # Composite confidence
                confidence = (
                    pred.confidence * 0.40
                    + (phys.indicators_agree / 4.0) * 0.30
                    + (1.0 - tox_signal.vpin) * 0.15
                    + self.calibrator.signal_quality * 0.15
                )

                # --- Check exit if in position ---
                if self.executor.in_position:
                    exit_info = await self.executor.check_exit(
                        price=price,
                        velocity=phys.velocity,
                        decel_magnitude=phys.decel_magnitude,
                        vpin=tox_signal.vpin,
                        liq_cascade=tox_signal.liq_cascade,
                        direction_signal=direction,
                    )
                    if exit_info:
                        self.journal.record(exit_info)
                        self.risk.update_equity(exit_info["pnl_usd"])
                        self.calibrator.update_trade(exit_info["pnl_pct"])
                        self.state_store.save(self.calibrator.save_state())
                        await self.telegram.notify_trade_exit(exit_info)

                # --- Check entry if flat ---
                elif risk_ok:
                    entry_info = await self.executor.check_entry(
                        price=price,
                        direction=direction,
                        confidence=confidence,
                        physics_agree=phys.indicators_agree,
                        regime_ok=self.regime.is_ok(),
                        toxicity_safe=tox_signal.safe_to_trade,
                        min_confidence=self.cfg.min_confidence,
                        min_physics=self.cfg.min_physics_agree,
                    )
                    if entry_info:
                        self.journal.record(entry_info)
                        await self.telegram.notify_trade_entry(entry_info)

                # --- Update dashboard state ---
                self._update_dashboard(
                    price=price,
                    pred=pred,
                    phys=phys,
                    tox=tox_signal,
                    flow=flow_signal,
                    drift=drift,
                    funding=funding,
                    direction=direction,
                    confidence=confidence,
                )

            except asyncio.CancelledError:
                return
            except Exception as e:
                logger.error("Signal loop error: {}", e)

            await asyncio.sleep(self.cfg.tick_interval_s)

    def _update_dashboard(self, **kwargs: Any) -> None:
        """Push current state to dashboard."""
        price = kwargs.get("price", 0)
        pred = kwargs.get("pred")
        phys = kwargs.get("phys")
        tox = kwargs.get("tox")
        flow = kwargs.get("flow")
        drift = kwargs.get("drift")
        funding = kwargs.get("funding")

        executor_status = self.executor.get_status()

        dashboard_state.update_many({
            "price": price,
            "position": executor_status.get("position"),
            "session_pnl": self.executor.session_pnl,
            "trade_count": self.executor.trade_count,
            "mode": self.cfg.mode,
            "regime": self.regime.get_status(),
            "physics": {
                "velocity": phys.velocity if phys else 0,
                "acceleration": phys.acceleration if phys else 0,
                "gravity": phys.gravity if phys else 0,
                "kinetic_energy": phys.kinetic_energy if phys else 0,
                "direction": phys.direction if phys else 0,
                "indicators_agree": phys.indicators_agree if phys else 0,
            },
            "calibrator": {
                "ema_win_rate": self.calibrator.state.ema_win_rate,
                "kelly_fraction": self.calibrator.state.kelly_fraction,
                "signal_quality": self.calibrator.signal_quality,
                "trade_count": self.calibrator.state.trade_count,
            },
            "signals": {
                "predictor_conf": pred.confidence if pred else 0,
                "physics_agree": phys.indicators_agree if phys else 0,
                "vpin": tox.vpin if tox else 0,
                "shield_safe": not self.regime.state.blocked,
                "funding_div": funding.divergence if funding else 0,
                "drift": drift.drift_magnitude if drift and drift.drift_detected else 0,
                "calibrator": self.calibrator.signal_quality,
                "flow_imb": flow.imbalance if flow else 0,
                "whale_count": len(self.whale.whale_events),
            },
            "risk": self.risk.get_status(),
            "trades": self.journal.read_last(20),
            "equity_curve": self.risk.get_equity_curve(),
            "uptime": time.time() - self._start_time,
        })

    async def _dashboard_broadcaster(self) -> None:
        """Push dashboard state to WebSocket clients periodically."""
        while self._running:
            await dashboard_state.broadcast()
            await asyncio.sleep(1.0)

    async def _cross_intel_loop(self) -> None:
        """Periodically fetch cross-exchange data."""
        while self._running:
            try:
                await self.cross_intel.fetch()
            except Exception as e:
                logger.debug("Cross-intel fetch error: {}", e)
            await asyncio.sleep(300)

    async def _daily_summary_loop(self) -> None:
        """Send daily summary via Telegram at midnight UTC."""
        while self._running:
            now = time.time()
            # Send once per day
            if now - self._daily_summary_sent > 86400:
                self._daily_summary_sent = now
                stats = {
                    **self.risk.get_status(),
                    "session_pnl": self.executor.session_pnl,
                    "trade_count": self.executor.trade_count,
                }
                await self.telegram.notify_daily_summary(stats)
            await asyncio.sleep(3600)

    def _get_full_status(self) -> dict[str, Any]:
        return {
            "mode": self.cfg.mode,
            "testnet": self.cfg.testnet,
            "uptime_s": time.time() - self._start_time,
            "price": dashboard_state.data.get("price", 0),
            "position": self.executor.get_status(),
            "risk": self.risk.get_status(),
            "regime": self.regime.get_status(),
            "calibrator": self.calibrator.state.to_dict(),
        }


class ShieldSnapshot:
    """Lightweight snapshot of shield state for the signal loop."""
    def __init__(self, ghost_count: int = 0, spoof_score: float = 0.0, safe: bool = True):
        self.ghost_count = ghost_count
        self.spoof_score = spoof_score
        self.safe = safe


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Apex NEO Trading System")
    parser.add_argument(
        "--mode",
        choices=["observe", "paper", "live"],
        default=None,
        help="Trading mode (overrides .env)",
    )
    return parser.parse_args()


async def main() -> None:
    args = parse_args()
    cfg = Config()

    if args.mode:
        cfg.mode = args.mode

    # Safety: live mode requires explicit confirmation
    if cfg.mode == "live":
        print("\n" + "=" * 50)
        print("WARNING: LIVE TRADING MODE")
        print(f"Testnet: {cfg.testnet}")
        print(f"Capital: ${cfg.capital}")
        print("=" * 50)
        confirm = input("Type 'CONFIRM LIVE' to proceed: ")
        if confirm != "CONFIRM LIVE":
            print("Aborted.")
            sys.exit(0)

    setup_logging(cfg.log_dir, cfg.log_level)

    neo = ApexNeo(cfg)

    # Handle shutdown signals
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, neo._request_stop)

    await neo.start()


if __name__ == "__main__":
    try:
        import uvloop
        uvloop.install()
    except ImportError:
        pass

    asyncio.run(main())
