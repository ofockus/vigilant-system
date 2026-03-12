"""
Fusion registry: plugs the v3 intelligence nodes into the v666 runtime.

The scanner uses this layer after local confluence passes. It can:
- veto contaminated opportunities (spoof / rug / contagion)
- penalize noisy setups (high ATR, extreme funding, thin volume)
- boost cleaner setups (safe assets, convergent regime, supportive narrative)

If the optional services are offline, the registry degrades gracefully to local heuristics.
"""
from __future__ import annotations

import asyncio
import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

from loguru import logger

from config.config import cfg
from core.service_clients import service_clients
from core.skill_bridge import OpenClawBinanceBridge
from services.liquidity_worm import liquidity_worm


@dataclass
class FusionDecision:
    allow: bool = True
    base_score: float = 0.0
    final_score: float = 0.0
    score_delta: float = 0.0
    vetoes: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    boosts: List[str] = field(default_factory=list)
    trace: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "allow": self.allow,
            "base_score": round(self.base_score, 2),
            "final_score": round(self.final_score, 2),
            "score_delta": round(self.score_delta, 2),
            "vetoes": self.vetoes,
            "warnings": self.warnings,
            "boosts": self.boosts,
            "trace": self.trace,
        }


@dataclass
class FusionSignalEnvelope:
    market: Dict[str, Any]
    confluence: Dict[str, Any] = field(default_factory=dict)
    spoof: Dict[str, Any] = field(default_factory=dict)
    rug: Dict[str, Any] = field(default_factory=dict)
    regime: Dict[str, Any] = field(default_factory=dict)
    narrative: Dict[str, Any] = field(default_factory=dict)
    macro: Dict[str, Any] = field(default_factory=dict)
    liquidity: Dict[str, Any] = field(default_factory=dict)
    decision: Dict[str, Any] = field(default_factory=dict)
    skill_handoff: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "market": self.market,
            "confluence": self.confluence,
            "spoof": self.spoof,
            "rug": self.rug,
            "regime": self.regime,
            "narrative": self.narrative,
            "macro": self.macro,
            "liquidity": self.liquidity,
            "decision": self.decision,
            "skill_handoff": self.skill_handoff,
        }


class FusionRegistry:
    def __init__(self) -> None:
        self._skill_bridge = OpenClawBinanceBridge(score_threshold=cfg.MIN_CONFLUENCE_SCORE)

    async def evaluate_opportunity(
        self,
        opportunity: Dict[str, Any],
        confluence_result: Any,
        orderbooks: Dict[str, Dict[str, Any]],
        tickers: Dict[str, Dict[str, Any]],
        markets: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> FusionSignalEnvelope:
        market_payload = self._build_market_payload(opportunity, orderbooks, tickers, markets or {})
        envelope = FusionSignalEnvelope(
            market=market_payload,
            confluence=self._serialize_confluence(confluence_result),
        )

        if not cfg.FUSION_ENABLED:
            decision = FusionDecision(
                allow=True,
                base_score=float(getattr(confluence_result, "score", 0.0)),
                final_score=float(getattr(confluence_result, "score", 0.0)),
                trace=["fusion_disabled"],
            )
            envelope.decision = decision.to_dict()
            envelope.skill_handoff = self._skill_bridge.build_handoff(
                market_payload,
                envelope.confluence,
                envelope.decision,
            )
            return envelope

        primary_asset = market_payload["primary_asset"]
        primary_symbol = market_payload["primary_symbol"]
        rug_metrics = self._build_antirug_metrics(market_payload)

        spoof_task = self._get_spoof(primary_symbol, orderbooks)
        rug_task = self._get_rug(primary_asset, primary_symbol, rug_metrics, tickers, markets or {})
        regime_task = self._get_regime(primary_asset, tickers, market_payload)
        narrative_task = self._get_narrative(primary_asset, market_payload)
        macro_task = self._get_macro(primary_symbol, tickers, market_payload)

        spoof, rug, regime, narrative, macro = await asyncio.gather(
            spoof_task,
            rug_task,
            regime_task,
            narrative_task,
            macro_task,
        )

        envelope.spoof = spoof
        envelope.rug = rug
        envelope.regime = regime
        envelope.narrative = narrative
        envelope.macro = macro
        envelope.liquidity = liquidity_worm.analyze(
            market=envelope.market,
            spoof=envelope.spoof,
            macro=envelope.macro,
            regime=envelope.regime,
        )

        decision = self._make_decision(envelope)
        envelope.decision = decision.to_dict()
        envelope.skill_handoff = self._skill_bridge.build_handoff(
            market_payload,
            envelope.confluence,
            envelope.decision,
        )
        return envelope

    def _build_market_payload(
        self,
        opportunity: Dict[str, Any],
        orderbooks: Dict[str, Dict[str, Any]],
        tickers: Dict[str, Dict[str, Any]],
        markets: Dict[str, Dict[str, Any]],
    ) -> Dict[str, Any]:
        legs = opportunity.get("legs", [])
        if legs and isinstance(legs[0], dict):
            path_assets = [legs[0].get("from", "")]
            path_assets.extend([leg.get("to", "") for leg in legs])
        else:
            path_assets = [part.strip() for part in str(opportunity.get("path", "")).split("→") if part.strip()]
            if not path_assets:
                path_assets = [part.strip() for part in str(opportunity.get("path", "")).replace(" ", "").split("→") if part.strip()]

        non_quote_assets = [
            asset for asset in path_assets
            if asset and asset not in cfg.QUOTE_ASSETS
        ]
        primary_asset = non_quote_assets[0] if non_quote_assets else (
            path_assets[1] if len(path_assets) > 1 else "BTC"
        )

        primary_symbol = ""
        for leg in legs:
            sym = leg.get("symbol", "")
            if primary_asset and primary_asset in sym.replace("/", "").replace(":", ""):
                primary_symbol = sym
                break
        if not primary_symbol and legs:
            primary_symbol = legs[0].get("symbol", "")

        quote_volume_total = 0.0
        spread_bps: Dict[str, float] = {}
        for leg in legs:
            sym = leg.get("symbol", "")
            tk = tickers.get(sym, {})
            ob = orderbooks.get(sym, {})
            quote_volume_total += float(tk.get("quoteVolume", 0) or 0)

            bids = ob.get("bids", [])
            asks = ob.get("asks", [])
            if bids and asks and bids[0][0]:
                spread_bps[sym] = round(((asks[0][0] - bids[0][0]) / bids[0][0]) * 10_000, 2)
            else:
                spread_bps[sym] = 0.0

        clean_primary_symbol = primary_symbol.replace("/", "").replace(":", "")
        if clean_primary_symbol and clean_primary_symbol not in clean_primary_symbol[-4:]:
            pass

        market = markets.get(primary_symbol) or {}
        return {
            "id": opportunity.get("id"),
            "path": opportunity.get("path", ""),
            "legs": legs,
            "net_pct": float(opportunity.get("net_pct", 0) or 0),
            "net_usd": float(opportunity.get("net_usd", 0) or 0),
            "capital_needed": float(opportunity.get("capital_needed", 0) or 0),
            "primary_asset": primary_asset,
            "primary_symbol": clean_primary_symbol or primary_symbol,
            "quote_volume_total": round(quote_volume_total, 2),
            "per_leg_spread_bps": spread_bps,
            "market_active": bool(market.get("active", True)),
            "market_spot": bool(market.get("spot", True)),
        }

    def _serialize_confluence(self, result: Any) -> Dict[str, Any]:
        details = getattr(result, "details", {}) or {}
        return {
            "score": round(float(getattr(result, "score", 0.0)), 2),
            "is_valid": bool(getattr(result, "is_valid", False)),
            "fake_momentum_flag": bool(getattr(result, "fake_momentum_flag", False)),
            "reversal_risk": round(float(getattr(result, "reversal_risk", 0.0)), 4),
            "book_entropy": round(float(getattr(result, "book_entropy", 0.0)), 4),
            "details": details,
        }

    async def _get_spoof(
        self,
        primary_symbol: str,
        orderbooks: Dict[str, Dict[str, Any]],
    ) -> Dict[str, Any]:
        if service_clients.enabled("spoofhunter"):
            try:
                data = await service_clients.get_spoof_state(primary_symbol)
                if data:
                    data["_source"] = "remote"
                    return data
            except Exception as exc:
                logger.debug(f"spoofhunter unavailable: {exc}")

        clean = primary_symbol.replace("/", "").replace(":", "")
        ob = (
            orderbooks.get(primary_symbol)
            or orderbooks.get(clean)
            or {}
        )
        return self._local_spoof_state(clean or primary_symbol, ob)

    async def _get_rug(
        self,
        primary_asset: str,
        primary_symbol: str,
        metrics: Dict[str, Any],
        tickers: Dict[str, Dict[str, Any]],
        markets: Dict[str, Dict[str, Any]],
    ) -> Dict[str, Any]:
        if service_clients.enabled("antirug"):
            try:
                data = await service_clients.analyze_token(metrics)
                if data:
                    data["_source"] = "remote"
                    return data
            except Exception as exc:
                logger.debug(f"antirug unavailable: {exc}")

        return self._local_rug_state(primary_asset, primary_symbol, metrics, tickers, markets)

    async def _get_regime(
        self,
        primary_asset: str,
        tickers: Dict[str, Dict[str, Any]],
        market_payload: Dict[str, Any],
    ) -> Dict[str, Any]:
        if service_clients.enabled("newtonian"):
            try:
                data = await service_clients.get_regime_state(primary_asset)
                if data:
                    data["_source"] = "remote"
                    return data
            except Exception as exc:
                logger.debug(f"newtonian unavailable: {exc}")

        legs = market_payload.get("legs", [])
        pcts = [
            float(tickers.get(leg.get("symbol", ""), {}).get("percentage", 0) or 0)
            for leg in legs
        ]
        avg_move = sum(pcts) / max(1, len(pcts))
        dispersion = (max(pcts) - min(pcts)) if pcts else 0.0
        regime = "CONVERGENCE" if dispersion < 1.25 else "DIVERGENCE"
        action = "EXECUTE" if regime == "CONVERGENCE" else "WAIT"
        if abs(avg_move) > 5.0 and dispersion < 0.5:
            regime = "CONTAGION"
            action = "KILL"
        return {
            "action": action,
            "side": "LONG" if avg_move >= 0 else "SHORT",
            "confidence": round(min(1.0, abs(avg_move) / 6.0 + max(0.0, 1.25 - dispersion) * 0.2), 4),
            "regime": regime,
            "pairs": [],
            "_source": "local",
        }

    async def _get_narrative(
        self,
        primary_asset: str,
        market_payload: Dict[str, Any],
    ) -> Dict[str, Any]:
        if service_clients.enabled("narrative"):
            try:
                data = await service_clients.get_narrative_state(primary_asset)
                if data:
                    data["_source"] = "remote"
                    return data
            except Exception as exc:
                logger.debug(f"narrative unavailable: {exc}")

        edge = market_payload.get("net_pct", 0.0)
        score = max(-1.0, min(1.0, edge / 0.50))
        conf = max(0.0, min(0.45, abs(score) * 0.35))
        return {
            "action": "WAIT",
            "side": "NONE",
            "confidence": round(conf, 4),
            "sentiment_score": round(score * 0.35, 4),
            "sentiment_volume": 0,
            "narrative_divergence": {
                "divergence": False,
                "direction": "NONE",
                "magnitude": 0.0,
            },
            "_source": "local",
        }

    async def _get_macro(
        self,
        primary_symbol: str,
        tickers: Dict[str, Dict[str, Any]],
        market_payload: Dict[str, Any],
    ) -> Dict[str, Any]:
        if service_clients.enabled("econopredator"):
            try:
                data = await service_clients.get_macro_state(primary_symbol)
                if data:
                    data["_source"] = "remote"
                    return data
            except Exception as exc:
                logger.debug(f"econopredator unavailable: {exc}")

        tk = tickers.get(primary_symbol) or tickers.get(primary_symbol.replace("/", "")) or {}
        last = float(tk.get("last", 0) or tk.get("close", 0) or 0)
        high = float(tk.get("high", last) or last)
        low = float(tk.get("low", last) or last)
        atr_pct = 0.0 if last <= 0 else ((high - low) / last) * 100.0
        return {
            "symbol": primary_symbol.replace("/", "").replace(":", ""),
            "funding": {
                "mark_price": last,
                "funding_rate": 0.0,
                "next_funding_time": 0,
            },
            "open_interest": {
                "oi": 0.0,
                "oi_value_usd": 0.0,
                "oi_delta": 0.0,
            },
            "long_short_ratio": {
                "long_account": 0.5,
                "short_account": 0.5,
                "ratio": 1.0,
            },
            "atr": {
                "value": high - low,
                "pct": round(atr_pct, 4),
                "price": last,
                "period": 14,
                "interval": "1d",
            },
            "onchain": None,
            "_source": "local",
        }

    def _local_spoof_state(self, symbol: str, orderbook: Dict[str, Any]) -> Dict[str, Any]:
        bids = orderbook.get("bids", [])[:10]
        asks = orderbook.get("asks", [])[:10]
        if not bids or not asks:
            return {
                "symbol": symbol.upper(),
                "action": "WAIT",
                "side": "NONE",
                "confidence": 0.0,
                "ghost_walls_detected": 0,
                "ghost_wall_side": "NONE",
                "ghost_wall_intensity": "LOW",
                "orderbook_imbalance": 0.0,
                "iceberg_detected": False,
                "_source": "local",
            }

        best_bid, best_ask = float(bids[0][0]), float(asks[0][0])
        bid_vol = sum(float(level[1]) for level in bids)
        ask_vol = sum(float(level[1]) for level in asks)
        total = bid_vol + ask_vol
        imbalance = 0.0 if total <= 0 else (bid_vol - ask_vol) / total
        spread_bps = 0.0 if best_bid <= 0 else ((best_ask - best_bid) / best_bid) * 10_000

        extreme_ratio = max(
            max((float(level[1]) / max(1e-9, bid_vol)) for level in bids),
            max((float(level[1]) / max(1e-9, ask_vol)) for level in asks),
        )
        ghost_count = 0
        if spread_bps > 18:
            ghost_count += 1
        if extreme_ratio > 0.55:
            ghost_count += 1
        if abs(imbalance) > 0.35:
            ghost_count += 1

        side = "LONG" if imbalance > 0 else "SHORT" if imbalance < 0 else "NONE"
        intensity = "HIGH" if ghost_count >= 3 else "MED" if ghost_count == 2 else "LOW"
        confidence = min(1.0, abs(imbalance) * 0.7 + ghost_count * 0.12)
        return {
            "symbol": symbol.upper(),
            "action": "EXECUTE" if ghost_count >= 2 else "WAIT",
            "side": side,
            "confidence": round(confidence, 4),
            "ghost_walls_detected": ghost_count,
            "ghost_wall_side": side if ghost_count else "NONE",
            "ghost_wall_intensity": intensity,
            "orderbook_imbalance": round(imbalance, 4),
            "iceberg_detected": extreme_ratio > 0.72,
            "_source": "local",
        }

    def _local_rug_state(
        self,
        primary_asset: str,
        primary_symbol: str,
        metrics: Dict[str, Any],
        tickers: Dict[str, Dict[str, Any]],
        markets: Dict[str, Dict[str, Any]],
    ) -> Dict[str, Any]:
        risk_factors: List[str] = []
        rug_prob = 0.0

        clean_asset = primary_asset.upper()
        clean_symbol = primary_symbol.replace("/", "").replace(":", "").upper()

        volume_24h = float(metrics.get("volume_24h", 0.0) or 0.0)
        if volume_24h < cfg.FUSION_MIN_QUOTE_VOLUME_USD:
            rug_prob += 0.30
            risk_factors.append(f"low_quote_volume={volume_24h:.0f}")

        if clean_asset not in cfg.SAFE_BASE_ASSETS:
            rug_prob += 0.12
            risk_factors.append("non_safe_asset")

        if any(clean_asset.endswith(pat) for pat in cfg.LEVERAGED_TOKEN_PATTERNS):
            rug_prob += 0.80
            risk_factors.append("leveraged_token_pattern")

        tk = tickers.get(primary_symbol) or tickers.get(clean_symbol) or {}
        spread_pct = 0.0
        bid = float(tk.get("bid", 0) or 0)
        ask = float(tk.get("ask", 0) or 0)
        if bid > 0 and ask > 0:
            spread_pct = ((ask - bid) / bid) * 100.0
        if spread_pct > 0.75:
            rug_prob += 0.18
            risk_factors.append(f"wide_spread={spread_pct:.2f}%")

        market = markets.get(primary_symbol) or {}
        if market and (not market.get("active", True) or not market.get("spot", True)):
            rug_prob += 0.90
            risk_factors.append("inactive_or_non_spot_market")

        rug_prob = min(0.99, rug_prob)
        status = "REJEITADO" if rug_prob * 100.0 >= cfg.FUSION_RUG_BLOCK_PCT else "APROVADO"
        return {
            "status": status,
            "rug_probability_pct": round(rug_prob * 100.0, 2),
            "risk_factors": risk_factors,
            "edge_directive": (
                "Risco de token/mercado fino detectado." if status == "REJEITADO"
                else "Estrutura de liquidez aceitável."
            ),
            "model_type": "local_heuristic",
            "_source": "local",
        }

    def _build_antirug_metrics(self, market_payload: Dict[str, Any]) -> Dict[str, Any]:
        qv = float(market_payload.get("quote_volume_total", 0.0) or 0.0)
        return {
            "liquidity_usd": max(qv * 0.02, 0.0),
            "top_holder_pct": 0.0,
            "dev_wallet_tx_count": 0,
            "age_hours": 24 * 30,
            "volume_24h": qv,
            "holders_count": 0.0,
            "buy_tax_pct": 0.0,
            "sell_tax_pct": 0.0,
        }

    def _make_decision(self, envelope: FusionSignalEnvelope) -> FusionDecision:
        decision = FusionDecision()
        decision.base_score = float(envelope.confluence.get("score", 0.0) or 0.0)
        decision.final_score = decision.base_score

        spoof = envelope.spoof or {}
        rug = envelope.rug or {}
        regime = envelope.regime or {}
        narrative = envelope.narrative or {}
        macro = envelope.macro or {}
        market = envelope.market or {}

        if spoof.get("iceberg_detected"):
            decision.vetoes.append("spoof_iceberg_detected")
            decision.trace.append("veto:iceberg")
        ghost_count = int(spoof.get("ghost_walls_detected", 0) or 0)
        if ghost_count >= cfg.FUSION_SPOOF_MIN_GHOSTS and spoof.get("ghost_wall_intensity") in {"HIGH", "MED"}:
            decision.vetoes.append("spoof_ghost_walls")
            decision.trace.append(f"veto:ghosts={ghost_count}")
        elif abs(float(spoof.get("orderbook_imbalance", 0.0) or 0.0)) >= cfg.FUSION_SPOOF_IMBALANCE_WARN:
            decision.score_delta -= 6.0
            decision.warnings.append("orderbook_imbalance_warn")
            decision.trace.append("penalty:imbalance")

        rug_prob = float(rug.get("rug_probability_pct", 0.0) or 0.0)
        if str(rug.get("status", "")).upper() == "REJEITADO" or rug_prob >= cfg.FUSION_RUG_BLOCK_PCT:
            decision.vetoes.append("antirug_rejected")
            decision.trace.append(f"veto:rug={rug_prob:.1f}%")
        elif rug_prob >= cfg.FUSION_RUG_WARN_PCT:
            decision.score_delta -= 7.0
            decision.warnings.append("rug_warn")
            decision.trace.append(f"penalty:rug={rug_prob:.1f}%")
        else:
            decision.score_delta += 2.0
            decision.boosts.append("rug_clean")
            decision.trace.append("boost:rug_clean")

        regime_name = str(regime.get("regime", "UNKNOWN")).upper()
        if str(regime.get("action", "")).upper() == "KILL" or regime_name in {r.upper() for r in cfg.BLOCKED_REGIMES}:
            decision.vetoes.append(f"regime_{regime_name.lower()}")
            decision.trace.append(f"veto:regime={regime_name.lower()}")
        elif regime_name == "CONVERGENCE":
            decision.score_delta += 4.0
            decision.boosts.append("regime_convergence")
            decision.trace.append("boost:convergence")
        elif regime_name == "DIVERGENCE":
            decision.score_delta -= 1.5
            decision.warnings.append("regime_divergence")
            decision.trace.append("penalty:divergence")

        n_conf = float(narrative.get("confidence", 0.0) or 0.0)
        if str(narrative.get("action", "")).upper() == "EXECUTE" and n_conf >= 0.45:
            bonus = min(4.0, 1.5 + n_conf * 4.0)
            decision.score_delta += bonus
            decision.boosts.append("narrative_support")
            decision.trace.append(f"boost:narrative={n_conf:.2f}")
        elif n_conf >= 0.25:
            decision.score_delta += 1.0
            decision.trace.append("boost:narrative_light")

        atr_pct = float((((macro.get("atr") or {}).get("pct", 0.0)) or 0.0))
        if atr_pct >= cfg.FUSION_MAX_ATR_PCT:
            decision.score_delta -= 4.0
            decision.warnings.append("high_atr")
            decision.trace.append(f"penalty:atr={atr_pct:.2f}")

        funding_rate = float((((macro.get("funding") or {}).get("funding_rate", 0.0)) or 0.0))
        if abs(funding_rate) >= cfg.FUSION_MAX_ABS_FUNDING:
            decision.score_delta -= 2.0
            decision.warnings.append("extreme_funding")
            decision.trace.append(f"penalty:funding={funding_rate:.5f}")

        if float(market.get("quote_volume_total", 0.0) or 0.0) >= max(cfg.FUSION_MIN_QUOTE_VOLUME_USD * 4, 750_000):
            decision.score_delta += 1.5
            decision.boosts.append("strong_liquidity")
            decision.trace.append("boost:liquidity")


        liquidity = envelope.liquidity or {}
        crowding = liquidity.get("crowding_stress") or {}
        book = liquidity.get("book_integrity") or {}
        brk = liquidity.get("break_validation") or {}
        sweep = liquidity.get("sweep_detector") or {}
        probs = liquidity.get("probabilities") or {}

        crowding_score = float(crowding.get("crowding_score", 0.0) or 0.0)
        squeeze_score = float(crowding.get("squeeze_risk_score", 0.0) or 0.0)
        spoof_risk = float(book.get("spoof_risk", 0.0) or 0.0)
        wall_quality = float(book.get("wall_quality_score", 0.0) or 0.0)
        true_break_prob = float(brk.get("true_break_prob", 0.0) or 0.0)
        fail_break_prob = float(brk.get("failure_break_prob", 0.0) or 0.0)
        sweep_detected = bool(sweep.get("sweep_detected", False))
        reclaim_strength = float(sweep.get("reclaim_strength", 0.0) or 0.0)

        if spoof_risk >= 75:
            decision.vetoes.append("liquidity_spoof_risk_high")
            decision.trace.append(f"veto:spoof_risk={spoof_risk:.1f}")
        elif spoof_risk >= 55:
            decision.score_delta -= 5.0
            decision.warnings.append("liquidity_spoof_risk_warn")
            decision.trace.append(f"penalty:spoof_risk={spoof_risk:.1f}")

        if crowding_score >= 78:
            decision.score_delta -= 3.5
            decision.warnings.append("crowding_extreme")
            decision.trace.append(f"penalty:crowding={crowding_score:.1f}")

        if squeeze_score >= 82:
            decision.warnings.append("squeeze_risk_high")
            decision.trace.append(f"warn:squeeze={squeeze_score:.1f}")

        if sweep_detected and reclaim_strength >= 0.45 and fail_break_prob >= 0.55:
            decision.score_delta += 3.0
            decision.boosts.append("sweep_reclaim_reversal")
            decision.trace.append("boost:sweep_reclaim")

        if true_break_prob >= 0.68 and fail_break_prob <= 0.40 and wall_quality >= 45:
            decision.score_delta += 3.0
            decision.boosts.append("true_break_validation")
            decision.trace.append("boost:true_break")

        p_sweep = float(probs.get("p_sweep", 0.0) or 0.0)
        p_trend = float(probs.get("p_trend", 0.0) or 0.0)
        acceptance = float(brk.get("acceptance_score", 0.0) or 0.0)

        if p_sweep >= 0.66 and reclaim_strength >= 0.45:
            decision.score_delta += 2.0
            decision.boosts.append("prob_sweep_reversal")
            decision.trace.append(f"boost:p_sweep={p_sweep:.2f}")

        if p_trend >= 0.66 and acceptance >= 0.55:
            decision.score_delta += 2.0
            decision.boosts.append("prob_true_break")
            decision.trace.append(f"boost:p_trend={p_trend:.2f}")

        decision.final_score = max(0.0, min(100.0, decision.base_score + decision.score_delta))
        if not decision.vetoes and decision.final_score < cfg.FUSION_MIN_FINAL_SCORE:
            decision.allow = False
            decision.warnings.append("fusion_score_below_threshold")
            decision.trace.append(f"deny:score<{cfg.FUSION_MIN_FINAL_SCORE}")
        else:
            decision.allow = len(decision.vetoes) == 0

        return decision


fusion_registry = FusionRegistry()
