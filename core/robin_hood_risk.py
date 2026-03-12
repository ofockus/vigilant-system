"""
core/robin_hood_risk.py
APEX PREDATOR NEO v666 – Robin Hood Risk Engine

Regras invioláveis de proteção de capital:

 ┌─────────────────────────────────────────────────────────┐
 │ Drawdown total > 4.0%  → PAUSA TOTAL por 30 minutos    │
 │ Equity < 50% capital   → SHUTDOWN PERMANENTE            │
 │ Capital por ciclo      → nunca excede MAX_POR_CICLO     │
 │ Drawdown > 2%          → reduz tamanho proporcional     │
 └─────────────────────────────────────────────────────────┘

Publica alertas via Redis para sincronizar TODOS os serviços.
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Dict, List

from loguru import logger

from config.config import cfg
from utils.redis_pubsub import redis_bus


@dataclass
class TradeRecord:
    """Registro completo de uma execução de arbitragem."""
    triangle_id: str
    timestamp: float
    gross_profit: float
    net_profit: float
    capital_used: float
    legs_executed: int
    duration_ms: float


@dataclass
class RiskState:
    """Estado atual do motor de risco."""
    initial_capital: float = cfg.CAPITAL_TOTAL
    equity: float = cfg.CAPITAL_TOTAL
    peak_equity: float = cfg.CAPITAL_TOTAL
    total_pnl: float = 0.0
    trades_total: int = 0
    trades_won: int = 0
    trades_lost: int = 0
    paused: bool = False
    pause_until: float = 0.0
    pause_reason: str = ""
    shutdown: bool = False
    history: List[TradeRecord] = field(default_factory=list)


class RobinHoodRisk:
    """Motor de risco com pausa automática por drawdown."""

    def __init__(self) -> None:
        self.state = RiskState()
        self._lock = asyncio.Lock()

    # ───────────────────────────────────────────────────────
    # INICIALIZAÇÃO
    # ───────────────────────────────────────────────────────
    async def initialize(self, exchange_balance: float = None) -> None:
        """Inicializa com saldo real da exchange."""
        if exchange_balance and exchange_balance > 0:
            self.state.initial_capital = exchange_balance
            self.state.equity = exchange_balance
            self.state.peak_equity = exchange_balance
        logger.info(
            f"🛡️ Robin Hood Risk ativo | Capital: ${self.state.initial_capital:.2f} | "
            f"Max DD: {cfg.MAX_DRAWDOWN_PCT}% | Cooldown: {cfg.ROBIN_HOOD_COOLDOWN_S}s | "
            f"Max/ciclo: ${cfg.MAX_POR_CICLO:.2f}"
        )

    # ───────────────────────────────────────────────────────
    # MÉTRICAS
    # ───────────────────────────────────────────────────────
    @property
    def drawdown_pct(self) -> float:
        """Drawdown atual em % do pico de equity."""
        if self.state.peak_equity <= 0:
            return 0.0
        return max(
            0.0,
            (self.state.peak_equity - self.state.equity) / self.state.peak_equity * 100,
        )

    @property
    def win_rate(self) -> float:
        """Win rate em % das operações totais."""
        if self.state.trades_total == 0:
            return 0.0
        return (self.state.trades_won / self.state.trades_total) * 100

    # ───────────────────────────────────────────────────────
    # VERIFICAÇÃO DE PERMISSÃO
    # ───────────────────────────────────────────────────────
    @property
    def is_allowed(self) -> bool:
        """Pode abrir nova operação agora?"""
        # Shutdown permanente
        if self.state.shutdown:
            return False

        # Pausa temporária
        if self.state.paused:
            if time.time() < self.state.pause_until:
                return False
            # Pausa expirou — reativar
            self.state.paused = False
            self.state.pause_reason = ""
            logger.success("▶️ Robin Hood: pausa de 30min encerrada, operações liberadas")

        # Verificar drawdown
        dd = self.drawdown_pct
        if dd >= cfg.MAX_DRAWDOWN_PCT:
            asyncio.ensure_future(self._activate_pause(
                f"Drawdown {dd:.2f}% atingiu limite de {cfg.MAX_DRAWDOWN_PCT}%"
            ))
            return False

        # Shutdown por equity mínimo
        if self.state.equity < cfg.equity_shutdown:
            self.state.shutdown = True
            logger.critical(
                f"🚨 SHUTDOWN PERMANENTE: equity ${self.state.equity:.2f} < "
                f"50% de ${self.state.initial_capital:.2f}"
            )
            return False

        return True

    # ───────────────────────────────────────────────────────
    # TAMANHO DE ORDEM
    # ───────────────────────────────────────────────────────
    def max_order_size(self) -> float:
        """Tamanho máximo para próximo ciclo, reduzido por drawdown."""
        if not self.is_allowed:
            return 0.0

        # Base: menor entre MAX_POR_CICLO e 40% do equity atual
        base = min(cfg.MAX_POR_CICLO, self.state.equity * 0.40)

        # Redução proporcional ao drawdown (entre 2% e 4%)
        dd = self.drawdown_pct
        if dd > 2.0:
            reduction = ((dd - 2.0) / (cfg.MAX_DRAWDOWN_PCT - 2.0)) * 0.50
            base *= max(0.10, 1.0 - reduction)

        return max(0.0, base)

    # ───────────────────────────────────────────────────────
    # REGISTRO DE TRADE
    # ───────────────────────────────────────────────────────
    async def record_trade(self, rec: TradeRecord) -> None:
        """Registra resultado de trade e verifica drawdown."""
        async with self._lock:
            self.state.history.append(rec)
            self.state.trades_total += 1
            self.state.total_pnl += rec.net_profit
            self.state.equity += rec.net_profit

            if rec.net_profit > 0:
                self.state.trades_won += 1
            else:
                self.state.trades_lost += 1

            # Atualizar pico de equity
            if self.state.equity > self.state.peak_equity:
                self.state.peak_equity = self.state.equity

            emoji = "✅" if rec.net_profit > 0 else "❌"
            logger.info(
                f"{emoji} Trade #{self.state.trades_total} | "
                f"PnL: ${rec.net_profit:+.4f} | "
                f"Equity: ${self.state.equity:.2f} | "
                f"DD: {self.drawdown_pct:.2f}% | "
                f"WR: {self.win_rate:.0f}% ({self.state.trades_won}W/{self.state.trades_lost}L)"
            )

            # Checar drawdown pós-trade
            if self.drawdown_pct >= cfg.MAX_DRAWDOWN_PCT:
                await self._activate_pause(
                    f"Drawdown {self.drawdown_pct:.2f}% após trade #{self.state.trades_total}"
                )

    # ───────────────────────────────────────────────────────
    # PAUSA AUTOMÁTICA
    # ───────────────────────────────────────────────────────
    async def _activate_pause(self, reason: str) -> None:
        """Ativa pausa total de 30 minutos e publica alerta Redis."""
        if self.state.paused:
            return

        self.state.paused = True
        self.state.pause_until = time.time() + cfg.ROBIN_HOOD_COOLDOWN_S
        self.state.pause_reason = reason

        logger.warning(
            f"🚨 ROBIN HOOD ATIVADO | {reason} | "
            f"Pausa: {cfg.ROBIN_HOOD_COOLDOWN_S}s (30min) | "
            f"Equity: ${self.state.equity:.2f} | "
            f"DD: {self.drawdown_pct:.2f}%"
        )

        # Publicar alerta para todos os executores
        await redis_bus.publish(cfg.CH_RISK, {
            "type": "PAUSE",
            "reason": reason,
            "pause_until": self.state.pause_until,
            "equity": self.state.equity,
            "drawdown_pct": self.drawdown_pct,
        })

        # Salvar estado no Redis para consulta
        await redis_bus.set_state("risk_state", {
            "paused": True,
            "pause_until": self.state.pause_until,
            "reason": reason,
            "equity": self.state.equity,
            "drawdown_pct": self.drawdown_pct,
        }, ttl=cfg.ROBIN_HOOD_COOLDOWN_S + 120)

    async def trigger_pause(self, reason: str) -> None:
        """Public helper to trigger protective pause from external modules."""
        async with self._lock:
            await self._activate_pause(reason)


    # ───────────────────────────────────────────────────────
    # RESUMO
    # ───────────────────────────────────────────────────────
    def summary(self) -> Dict:
        """Resumo completo do estado de risco (para logs e heartbeat)."""
        return {
            "equity": round(self.state.equity, 4),
            "peak": round(self.state.peak_equity, 4),
            "pnl": round(self.state.total_pnl, 4),
            "dd_pct": round(self.drawdown_pct, 2),
            "trades": self.state.trades_total,
            "wins": self.state.trades_won,
            "losses": self.state.trades_lost,
            "wr": round(self.win_rate, 1),
            "paused": self.state.paused,
            "shutdown": self.state.shutdown,
            "max_order": round(self.max_order_size(), 4),
        }


# Singleton global
robin_hood = RobinHoodRisk()
