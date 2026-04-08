"""
PREDATOR v4 TOKYO — Core orchestrator.

Boots all subsystems, manages the signal loop per symbol, handles
position tracking across multiple pairs, and coordinates shutdown.

Modes:
  backtest — download data + replay
  paper    — real websockets, fake orders
  live     — real orders (requires confirmation)
"""

from __future__ import annotations

import asyncio
import signal
import sys
import time
from pathlib import Path
from typing import Any

from loguru import logger

from .config import Config
from .dashboard.server import run_server, state as dash_state
from .exchange.binance_ws import BinanceWS
from .exchange.bybit_ws import BybitWS
from .exchange.executor import Executor
from .exchange.symbols import SymbolSelector
from .risk.manager import RiskManager
from .strategy.exits import ExitManager, PositionState
from .strategy.features import FeatureEngine
from .strategy.model import PredictorModel
from .strategy.signals import SignalGenerator
from .telegram.bot import TelegramBot


class Predator:
    """Main orchestrator — multi-symbol scalping engine."""

    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        self._running = False
        self._start_time = time.time()

        # Exchange
        self.binance = BinanceWS(
            api_key=cfg.binance_api_key,
            api_secret=cfg.binance_api_secret,
            testnet=cfg.exchange.binance_testnet,
        )
        self.bybit = BybitWS(
            api_key=cfg.bybit_api_key,
            api_secret=cfg.bybit_api_secret,
            testnet=cfg.exchange.bybit_testnet,
        )

        # Symbol selection
        self.selector = SymbolSelector(
            pool=cfg.symbols.pool,
            max_active=cfg.symbols.max_active,
            min_volume=cfg.symbols.min_volume_24h,
            min_volatility=cfg.symbols.min_volatility_5m,
            refresh_s=cfg.symbols.refresh_interval_s,
        )

        # Strategy per symbol
        self.features: dict[str, FeatureEngine] = {}
        self.model = PredictorModel()
        self.signal_gen = SignalGenerator(
            min_confirmations=cfg.strategy.min_confirmations,
            min_model_confidence=cfg.strategy.min_model_confidence,
            min_book_imbalance=cfg.strategy.min_book_imbalance,
            min_flow_delta=cfg.strategy.min_flow_delta,
            decel_threshold=cfg.strategy.decel_threshold,
            ek_rev_threshold=cfg.strategy.ek_rev_threshold,
        )
        self.exit_mgr = ExitManager(
            min_hold_s=cfg.exit.min_hold_s,
            cooldown_s=cfg.exit.cooldown_s,
            stop_loss_pct=cfg.exit.stop_loss_pct,
            take_profit_base_pct=cfg.exit.take_profit_base_pct,
            trail_activation_pct=cfg.exit.trail_activation_pct,
            trail_callback_pct=cfg.exit.trail_callback_pct,
            max_hold_s=cfg.exit.max_hold_s,
            time_decay_start_s=cfg.exit.time_decay_start_s,
            grav_collapse_threshold=cfg.exit.grav_collapse_threshold,
            drift_exit_threshold=cfg.exit.drift_exit_threshold,
            decel_threshold=cfg.strategy.decel_threshold,
            vol_scale_sl=cfg.exit.vol_scale_sl,
            vol_scale_tp=cfg.exit.vol_scale_tp,
        )

        # Execution
        self.executor = Executor(
            mode=cfg.mode,
            binance=self.binance,
            taker_fee_pct=cfg.backtest.taker_fee_pct,
        )

        # Risk
        self.risk = RiskManager(
            capital=cfg.risk.starting_capital,
            max_risk_pct=cfg.risk.max_risk_per_trade_pct,
            leverage_min=cfg.risk.leverage_min,
            leverage_max=cfg.risk.leverage_max,
            leverage_dynamic=cfg.risk.leverage_dynamic,
            daily_loss_pct=cfg.risk.daily_loss_limit_pct,
            max_drawdown_pct=cfg.risk.max_drawdown_pct,
            max_concurrent=cfg.risk.max_concurrent_positions,
            pause_after_losses=cfg.risk.pause_after_consecutive_losses,
            pause_duration_s=cfg.risk.pause_duration_s,
        )

        # Telegram
        self.telegram = TelegramBot(
            token=cfg.telegram_token,
            chat_id=cfg.telegram_chat_id,
            enabled=cfg.telegram.enabled,
        )

        # Position tracking
        self.positions: dict[str, PositionState] = {}
        self.trade_history: list[dict] = []
        self.bybit_funding: dict[str, float] = {}
        self.binance_funding: dict[str, float] = {}

    async def start(self) -> None:
        """Boot everything and enter main loop."""
        logger.info("=" * 50)
        logger.info("PREDATOR v4 TOKYO | mode={}", self.cfg.mode)
        logger.info("=" * 50)

        # Load ML model if available
        self.model.load()

        # Select initial symbols
        active = await self.selector.refresh(self.binance.fetch_all_tickers)
        if not active:
            active = [s.upper() for s in self.cfg.symbols.pool[:self.cfg.symbols.max_active]]
            logger.warning("Symbol selection failed, using defaults: {}", active)

        # Initialize websockets with active symbols
        self.binance.symbols = [s.lower() for s in active]
        self.bybit.symbols = active

        # Initialize feature engines per symbol
        for sym in active:
            self.features[sym.lower()] = FeatureEngine(
                momentum_window=self.cfg.strategy.momentum_window_ticks,
                flow_window=self.cfg.strategy.flow_window_ticks,
                spread_ema_alpha=self.cfg.strategy.spread_ema_alpha,
            )

        # Set leverage for all symbols
        if self.cfg.mode == "live":
            for sym in active:
                try:
                    await self.binance.set_leverage(sym, self.cfg.risk.leverage_max)
                except Exception as e:
                    logger.warning("Failed to set leverage for {}: {}", sym, e)

        # Register trade callback
        self.binance.on_trade(self._on_trade)

        # Start subsystems
        await self.binance.start()
        await self.bybit.start()
        self._running = True

        await self.telegram.send(
            f"<b>PREDATOR v4 started</b>\n"
            f"Mode: {self.cfg.mode}\n"
            f"Symbols: {', '.join(active)}\n"
            f"Capital: ${self.cfg.risk.starting_capital}"
        )

        # Launch concurrent tasks
        tasks = [
            asyncio.create_task(self._signal_loop(), name="signal_loop"),
            asyncio.create_task(self._funding_loop(), name="funding"),
            asyncio.create_task(self._symbol_refresh_loop(), name="sym_refresh"),
            asyncio.create_task(self._dashboard_loop(), name="dashboard_bc"),
            asyncio.create_task(run_server(self.cfg.dashboard.host, self.cfg.dashboard.port),
                                name="dashboard"),
            asyncio.create_task(self._daily_summary_loop(), name="daily"),
        ]

        try:
            await asyncio.gather(*tasks)
        except asyncio.CancelledError:
            pass
        finally:
            await self.shutdown()

    async def shutdown(self) -> None:
        logger.info("Shutting down...")
        self._running = False
        await self.telegram.send("<b>PREDATOR v4 stopped</b>")
        await self.telegram.close()
        await self.binance.stop()
        await self.bybit.stop()

    def _request_stop(self) -> None:
        self._running = False

    # ─── Trade callback (fed by WebSocket) ────────────────

    async def _on_trade(self, trade: Any) -> None:
        """Called for every aggTrade from Binance WS."""
        sym = trade.symbol
        fe = self.features.get(sym)
        if fe is None:
            return
        is_buy = not trade.is_buyer_maker
        fe.add_trade(sym, trade.price, trade.qty, is_buy, trade.timestamp)

    # ─── Main signal loop ─────────────────────────────────

    async def _signal_loop(self) -> None:
        """Core loop: check exits then entries for all symbols."""
        await asyncio.sleep(3)  # let WS streams initialize
        logger.info("Signal loop started")

        while self._running:
            try:
                for sym in list(self.binance.symbols):
                    book = self.binance.books.get(sym)
                    fe = self.features.get(sym)
                    if not book or not fe or book.mid <= 0:
                        continue

                    price = book.mid
                    bids = book.top_bids(20)
                    asks = book.top_asks(20)

                    # 1s kline feed from WS
                    klines = self.binance.klines_1s.get(sym, [])
                    if klines:
                        last_k = klines[-1]
                        if last_k.get("closed"):
                            fe.add_kline(sym, last_k["c"], last_k["h"], last_k["l"])

                    # Compute features
                    b_fund = self.binance_funding.get(sym.upper(), 0)
                    by_fund = self.bybit_funding.get(sym.upper(), 0)
                    fv = fe.compute(sym, bids, asks, book.spread_pct, b_fund, by_fund)

                    # ML prediction
                    direction, confidence = self.model.predict(fv)

                    # --- Exit check ---
                    if sym in self.positions:
                        pos = self.positions[sym]
                        exit_dec = self.exit_mgr.check(pos, fv, price, direction)

                        if exit_dec.should_exit:
                            fill = await self.executor.market_exit(
                                sym.upper(),
                                "BUY" if pos.side == 1 else "SELL",
                                pos.qty, price,
                            )
                            if fill.success:
                                # Calculate PnL
                                if pos.side == 1:
                                    pnl_pct = (fill.price - pos.entry_price) / pos.entry_price * 100
                                else:
                                    pnl_pct = (pos.entry_price - fill.price) / pos.entry_price * 100
                                pnl_pct -= self.executor.taker_fee_pct * 2 / 100 * 100

                                notional = pos.qty * pos.entry_price
                                pnl_usd = pnl_pct / 100 * notional
                                hold_s = time.time() - pos.entry_time

                                self.risk.record_trade(pnl_usd)
                                self.risk.open_positions -= 1
                                self.exit_mgr.record_exit()
                                del self.positions[sym]

                                trade_rec = {
                                    "symbol": sym, "side": pos.side,
                                    "entry_price": pos.entry_price,
                                    "exit_price": fill.price,
                                    "pnl_pct": pnl_pct, "pnl_usd": pnl_usd,
                                    "hold_time_s": hold_s,
                                    "exit_reason": exit_dec.reason,
                                    "exit_time": time.time(),
                                }
                                self.trade_history.append(trade_rec)

                                side_str = "LONG" if pos.side == 1 else "SHORT"
                                logger.info(
                                    "EXIT {} {} | {} @ {:.2f} → {:.2f} | PnL={:+.3f}% ${:+.4f} | {:.1f}s",
                                    exit_dec.reason, sym.upper(), side_str,
                                    pos.entry_price, fill.price,
                                    pnl_pct, pnl_usd, hold_s,
                                )
                                await self.telegram.notify_exit(
                                    sym.upper(), side_str, pnl_pct, pnl_usd,
                                    hold_s, exit_dec.reason,
                                )

                        continue  # don't check entry while in position for this sym

                    # --- Entry check ---
                    ok, reason = self.risk.check_allowed()
                    if not ok:
                        continue
                    if self.exit_mgr.on_cooldown:
                        continue

                    signal = self.signal_gen.evaluate(fv, direction, confidence)
                    if signal.direction == 0:
                        continue

                    # Position sizing
                    leverage = self.risk.compute_leverage(fv.micro_vol)
                    qty = self.risk.compute_position_size(price, fv.atr_proxy, leverage)
                    if qty <= 0:
                        continue

                    side_str = "BUY" if signal.direction == 1 else "SELL"
                    fill = await self.executor.market_entry(
                        sym.upper(), side_str, qty, price,
                    )

                    if fill.success:
                        self.positions[sym] = PositionState(
                            symbol=sym, side=signal.direction,
                            entry_price=fill.price, entry_time=time.time(),
                            qty=fill.qty, leverage=leverage,
                        )
                        self.risk.open_positions += 1

                        logger.info(
                            "ENTRY {} {} | {:.6f} @ {:.2f} | lev={}x | conf={:.2f}",
                            side_str, sym.upper(), fill.qty, fill.price,
                            leverage, confidence,
                        )
                        await self.telegram.notify_entry(
                            sym.upper(), side_str, fill.price, fill.qty,
                            confidence, self.cfg.mode,
                        )

            except asyncio.CancelledError:
                return
            except Exception as e:
                logger.error("Signal loop error: {}", e)
                await self.telegram.notify_error(str(e))

            await asyncio.sleep(0.1)  # 100ms tick — matches depth@100ms

    # ─── Background tasks ─────────────────────────────────

    async def _funding_loop(self) -> None:
        """Fetch funding rates periodically."""
        while self._running:
            try:
                self.bybit_funding = await self.bybit.fetch_funding_rates()
                # Binance funding from premium index
                for sym in self.binance.symbols:
                    try:
                        data = await self.binance._rest_get(
                            "/fapi/v1/premiumIndex",
                            {"symbol": sym.upper()},
                        )
                        self.binance_funding[sym.upper()] = float(data.get("lastFundingRate", 0))
                    except Exception:
                        pass
            except Exception as e:
                logger.debug("Funding fetch error: {}", e)
            await asyncio.sleep(300)

    async def _symbol_refresh_loop(self) -> None:
        """Refresh active symbol set periodically."""
        while self._running:
            await asyncio.sleep(self.cfg.symbols.refresh_interval_s)
            try:
                new_active = await self.selector.refresh(self.binance.fetch_all_tickers)
                # Update websocket subscriptions if changed
                new_lower = [s.lower() for s in new_active]
                if set(new_lower) != set(self.binance.symbols):
                    logger.info("Symbol set changed: {}", new_active)
                    # Would need to reconnect WS to change subscriptions
                    # For now just update feature engines
                    for sym in new_lower:
                        if sym not in self.features:
                            self.features[sym] = FeatureEngine(
                                momentum_window=self.cfg.strategy.momentum_window_ticks,
                                flow_window=self.cfg.strategy.flow_window_ticks,
                            )
            except Exception as e:
                logger.debug("Symbol refresh error: {}", e)

    async def _dashboard_loop(self) -> None:
        """Push state to dashboard clients."""
        while self._running:
            pos_list = [
                {"symbol": p.symbol, "side": p.side, "entry": p.entry_price,
                 "pnl": (self.binance.books[p.symbol].mid - p.entry_price) / p.entry_price * 100
                 if p.side == 1 else
                 (p.entry_price - self.binance.books[p.symbol].mid) / p.entry_price * 100
                 if p.symbol in self.binance.books and self.binance.books[p.symbol].mid > 0
                 else 0}
                for p in self.positions.values()
            ]
            dash_state.update({
                "mode": self.cfg.mode,
                "risk": self.risk.get_status(),
                "positions": pos_list,
                "active_symbols": [s.upper() for s in self.binance.symbols],
                "trades": self.trade_history[-20:],
                "equity_curve": self.risk.state.equity_curve[-500:],
                "uptime": time.time() - self._start_time,
            })
            await dash_state.broadcast()
            await asyncio.sleep(1)

    async def _daily_summary_loop(self) -> None:
        """Send daily Telegram summary."""
        while self._running:
            await asyncio.sleep(3600)
            now = time.time()
            if now - self.risk.state.day_start_ts > 82800:  # ~23 hours
                await self.telegram.notify_daily(self.risk.get_status())
