"""
scanners/dynamic_tri_scanner.py
APEX PREDATOR NEO v666 – Scanner Dinâmico de Arbitragem Triangular

Descobre automaticamente triângulos de 3 pernas lucrativos
na Binance Spot. Scan contínuo com cálculo de profit
real após 3× taxas (maker+taker).

Fluxo por ciclo:
 1. Atualiza tickers batch (cache 150ms)
 2. Avalia cada triângulo com preços bid/ask
 3. Pré-filtra por profit mínimo
 4. Busca orderbooks sob demanda para candidatos
 5. Roda ConfluenceEngine local
 6. Roda FusionRegistry (spoof / antirug / regime / narrative / macro)
 7. Publica a melhor oportunidade via Redis
"""
from __future__ import annotations

import asyncio
import random
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

from loguru import logger

from config.config import cfg
from core.binance_connector import connector
from core.confluence_engine import confluence
from core.fusion_registry import fusion_registry
from core.robin_hood_risk import robin_hood
from utils.redis_pubsub import redis_bus


@dataclass
class TriangleLeg:
    """Uma perna do triângulo de arbitragem."""
    symbol: str
    side: str
    from_asset: str
    to_asset: str


@dataclass
class TriangleOpportunity:
    """Oportunidade de arbitragem triangular completa."""
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    legs: List[TriangleLeg] = field(default_factory=list)
    path: str = ""
    gross_pct: float = 0.0
    net_pct: float = 0.0
    net_usd: float = 0.0
    confluence_score: float = 0.0
    capital: float = 0.0
    timestamp: float = field(default_factory=time.time)
    base_confluence_score: float = 0.0
    fusion: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        decision = self.fusion.get("decision", {}) if self.fusion else {}
        return {
            "id": self.id,
            "path": self.path,
            "legs": [
                {
                    "symbol": leg.symbol,
                    "side": leg.side,
                    "from": leg.from_asset,
                    "to": leg.to_asset,
                }
                for leg in self.legs
            ],
            "gross_pct": round(self.gross_pct, 5),
            "net_pct": round(self.net_pct, 5),
            "net_usd": round(self.net_usd, 6),
            "confluence_score": round(self.confluence_score, 1),
            "base_confluence_score": round(self.base_confluence_score, 1),
            "capital_needed": round(self.capital, 4),
            "timestamp": self.timestamp,
            "fusion": self.fusion,
            "decision": decision,
            "final_score": round(float(decision.get("final_score", self.confluence_score) or self.confluence_score), 2),
        }


class DynamicTriScanner:
    """Scanner que descobre e avalia triângulos automaticamente."""

    def __init__(self) -> None:
        self._triangles: List[List[TriangleLeg]] = []
        self._running: bool = False
        self._total_scans: int = 0
        self._total_hits: int = 0
        self._vetoed_hits: int = 0
        self._tickers: Dict[str, Dict] = {}
        self._tickers_ts: float = 0.0

    async def discover(self) -> int:
        """Constroi grafo de pares e encontra todos os ciclos de 3 vértices."""
        logger.info("🔍 Descobrindo triângulos possíveis...")
        t0 = time.time()
        markets = connector.markets

        graph: Dict[str, Dict[str, tuple]] = {}
        all_assets = set(cfg.BASE_ASSETS) | set(cfg.QUOTE_ASSETS)

        for sym, market in markets.items():
            if not market.get("active") or not market.get("spot"):
                continue

            base = market.get("base", "")
            quote = market.get("quote", "")
            if not base or not quote:
                continue

            if base not in all_assets and quote not in all_assets:
                continue

            graph.setdefault(base, {})[quote] = (sym, "sell")
            graph.setdefault(quote, {})[base] = (sym, "buy")

        found: List[List[TriangleLeg]] = []
        seen_keys: Set[frozenset] = set()

        for start in cfg.QUOTE_ASSETS:
            if start not in graph:
                continue
            for mid_a in graph[start]:
                if mid_a == start:
                    continue
                for mid_b in graph.get(mid_a, {}):
                    if mid_b == start or mid_b == mid_a:
                        continue
                    if start not in graph.get(mid_b, {}):
                        continue

                    sym1, side1 = graph[start][mid_a]
                    sym2, side2 = graph[mid_a][mid_b]
                    sym3, side3 = graph[mid_b][start]

                    key = frozenset({sym1, sym2, sym3})
                    if key in seen_keys:
                        continue
                    seen_keys.add(key)

                    found.append([
                        TriangleLeg(sym1, side1, start, mid_a),
                        TriangleLeg(sym2, side2, mid_a, mid_b),
                        TriangleLeg(sym3, side3, mid_b, start),
                    ])

        self._triangles = found
        elapsed = time.time() - t0
        logger.success(
            f"✅ {len(found)} triângulos únicos descobertos em {elapsed:.3f}s | "
            f"Grafo: {len(graph)} nós"
        )

        for tri in found[:10]:
            path = f"{tri[0].from_asset}→{tri[0].to_asset}→{tri[1].to_asset}→{tri[2].to_asset}"
            syms = f"({tri[0].symbol}, {tri[1].symbol}, {tri[2].symbol})"
            logger.info(f"   📐 {path} {syms}")

        if len(found) > 10:
            logger.info(f"   ... e mais {len(found) - 10} triângulos")

        return len(found)

    async def run(self) -> None:
        """Loop principal: avalia triângulos a cada SCAN_INTERVAL_MS."""
        self._running = True
        interval_s = cfg.SCAN_INTERVAL_MS / 1000.0
        last_heartbeat = time.time()

        logger.info(
            f"🚀 Scanner v666 rodando | "
            f"{len(self._triangles)} triângulos | "
            f"Intervalo: {cfg.SCAN_INTERVAL_MS}ms | "
            f"Min profit: {cfg.MIN_PROFIT_PCT}% | "
            f"Min score: {cfg.MIN_CONFLUENCE_SCORE} | "
            f"Fusion: {cfg.FUSION_ENABLED}"
        )

        while self._running:
            cycle_start = time.time()

            try:
                best = await self._scan_cycle()

                if best:
                    payload = best.to_dict()
                    receivers = await redis_bus.publish(cfg.CH_OPPORTUNITIES, payload)
                    await redis_bus.publish(cfg.CH_DECISIONS, {
                        "type": "APPROVED",
                        "id": best.id,
                        "path": best.path,
                        "score": payload.get("final_score"),
                        "fusion": payload.get("fusion", {}),
                    })
                    logger.info(
                        f"🎯 #{best.id} | {best.path} | "
                        f"{best.net_pct:+.4f}% (${best.net_usd:+.6f}) | "
                        f"Score: {best.confluence_score:.0f} | "
                        f"Recv: {receivers}"
                    )

                now = time.time()
                if now - last_heartbeat > 30:
                    await redis_bus.heartbeat({
                        "scans": self._total_scans,
                        "hits": self._total_hits,
                        "vetoed": self._vetoed_hits,
                        "triangles": len(self._triangles),
                        "risk": robin_hood.summary(),
                    })
                    last_heartbeat = now

            except Exception as exc:
                logger.error(f"Erro no ciclo de scan: {exc}")

            elapsed = time.time() - cycle_start
            sleep_time = max(0, interval_s - elapsed)
            jitter = random.uniform(cfg.REQUEST_JITTER_MIN, cfg.REQUEST_JITTER_MAX)
            await asyncio.sleep(sleep_time * jitter)

    def stop(self) -> None:
        self._running = False
        logger.info("🛑 Scanner parado")

    async def _scan_cycle(self) -> Optional[TriangleOpportunity]:
        """Avalia todos os triângulos e retorna o melhor qualificado."""
        if not self._triangles:
            return None
        if not robin_hood.is_allowed:
            return None

        now = time.time()
        if now - self._tickers_ts > 0.15:
            self._tickers = await connector.fetch_all_tickers()
            self._tickers_ts = now

        best: Optional[TriangleOpportunity] = None
        best_combined_score: float = 0.0
        candles_cache: Dict[str, Any] = {}

        for tri in self._triangles:
            opp = self._quick_evaluate(tri)
            if not opp or opp.net_pct < cfg.MIN_PROFIT_PCT:
                continue

            orderbooks: Dict[str, Dict] = {}
            ob_tasks = [connector.fetch_orderbook(leg.symbol, 10) for leg in tri]
            ob_results = await asyncio.gather(*ob_tasks, return_exceptions=True)
            for leg, ob in zip(tri, ob_results):
                if isinstance(ob, Exception):
                    logger.debug(f"orderbook_error symbol={leg.symbol} err={type(ob).__name__}")
                    continue
                if ob:
                    orderbooks[leg.symbol] = ob

            tri_data = {
                "legs": [{"symbol": leg.symbol, "side": leg.side} for leg in tri],
                "net_profit_pct": opp.net_pct,
            }
            conf_result = confluence.analyze(tri_data, orderbooks, self._tickers)
            if not conf_result.is_valid:
                continue

            chart_symbol = self._select_chart_symbol(tri)
            candles_by_symbol: Dict[str, Any] = {}
            if chart_symbol:
                if chart_symbol not in candles_cache:
                    candles_cache[chart_symbol] = await connector.fetch_ohlcv(
                        chart_symbol,
                        timeframe="15m",
                        limit=96,
                        ttl=20.0,
                    )
                if candles_cache.get(chart_symbol):
                    candles_by_symbol[chart_symbol] = candles_cache[chart_symbol]
                    conf_result = confluence.analyze(
                        tri_data,
                        orderbooks,
                        self._tickers,
                        candles_by_symbol=candles_by_symbol,
                    )
                    if not conf_result.is_valid:
                        continue

            opp.base_confluence_score = conf_result.score

            fusion = await fusion_registry.evaluate_opportunity(
                opportunity=opp.to_dict(),
                confluence_result=conf_result,
                orderbooks=orderbooks,
                tickers=self._tickers,
                markets=connector.markets,
            )

            decision = fusion.decision or {}
            if not decision.get("allow", True):
                self._vetoed_hits += 1
                await redis_bus.publish(cfg.CH_DECISIONS, {
                    "type": "REJECTED",
                    "id": opp.id,
                    "path": opp.path,
                    "reason": decision.get("vetoes") or decision.get("warnings") or ["unknown"],
                    "fusion": fusion.to_dict(),
                })
                logger.debug(
                    f"🚫 #{opp.id} {opp.path} vetado | "
                    f"{decision.get('vetoes') or decision.get('warnings')}"
                )
                continue

            opp.fusion = fusion.to_dict()
            opp.confluence_score = float(decision.get("final_score", conf_result.score) or conf_result.score)

            wvi = float((((opp.fusion.get("liquidity") or {}).get("crowding_stress") or {}).get("wvi", 0.0) or 0.0))
            if wvi >= cfg.WVI_PAUSE_THRESHOLD:
                await robin_hood.trigger_pause(f"WVI {wvi:.2f} acima do limite {cfg.WVI_PAUSE_THRESHOLD:.2f}")
                logger.warning(f"wvi_pause_triggered id={opp.id} wvi={wvi:.2f}")
                continue

            snipe_boost = self._narrative_snipe_boost(opp, self._tickers)
            combined = opp.net_pct * ((opp.confluence_score + snipe_boost) / 100.0)
            if combined > best_combined_score:
                best_combined_score = combined
                best = opp

        self._total_scans += 1
        if best:
            self._total_hits += 1
        return best

    def _quick_evaluate(self, tri: List[TriangleLeg]) -> Optional[TriangleOpportunity]:
        amount = 1.0
        fee = cfg.fee_per_leg
        path_parts = [tri[0].from_asset]

        for leg in tri:
            tk = self._tickers.get(leg.symbol, {})
            bid = float(tk.get("bid", 0) or 0)
            ask = float(tk.get("ask", 0) or 0)

            if bid <= 0 or ask <= 0:
                return None

            if leg.side == "buy":
                amount = (amount / ask) * (1.0 - fee)
            else:
                amount = (amount * bid) * (1.0 - fee)

            path_parts.append(leg.to_asset)

        net_pct = (amount - 1.0) * 100.0

        cap = robin_hood.max_order_size()
        if cap < 1.0:
            return None

        opp = TriangleOpportunity()
        opp.legs = tri
        opp.path = " → ".join(path_parts)
        opp.gross_pct = net_pct + (cfg.fee_3_legs * 100.0)
        opp.net_pct = net_pct
        opp.capital = min(cap, cfg.MAX_POR_CICLO)
        opp.net_usd = opp.capital * (net_pct / 100.0)
        return opp

    def stats(self) -> Dict:
        return {
            "triangles": len(self._triangles),
            "scans": self._total_scans,
            "hits": self._total_hits,
            "vetoed": self._vetoed_hits,
            "hit_rate_pct": round((self._total_hits / max(1, self._total_scans)) * 100, 2),
            "running": self._running,
        }

    def _select_chart_symbol(self, tri: List[TriangleLeg]) -> Optional[str]:
        non_quote_legs = [leg for leg in tri if leg.to_asset not in cfg.QUOTE_ASSETS or leg.from_asset not in cfg.QUOTE_ASSETS]
        for leg in non_quote_legs:
            if connector.symbol_exists(leg.symbol):
                return leg.symbol
        for leg in tri:
            if connector.symbol_exists(leg.symbol):
                return leg.symbol
        return tri[0].symbol if tri else None


    def _narrative_snipe_boost(self, opp: TriangleOpportunity, tickers: Dict[str, Dict]) -> float:
        """Simple narrative sniping: volume surge + momentum anomaly."""
        total_qv = 0.0
        max_pct = 0.0
        for leg in opp.legs:
            tk = tickers.get(leg.symbol, {})
            total_qv += float(tk.get("quoteVolume", 0) or 0)
            max_pct = max(max_pct, abs(float(tk.get("percentage", 0) or 0)))

        if total_qv >= 8_000_000 and max_pct >= 3.5:
            return 4.0
        if total_qv >= 3_000_000 and max_pct >= 2.0:
            return 2.0
        return 0.0


scanner = DynamicTriScanner()
