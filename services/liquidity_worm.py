"""Production-style liquidity engine for fusion decision support.

Framework:
- Liquidity map
- WVI split (crowding + instability)
- Sweep/Trend probabilities
- Acceptance score
- Trigger classifier
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Dict, List


@dataclass
class LiquidityWormService:
    round_step_bps: float = 25.0
    # LiquidityScore weights
    w1: float = 0.20
    w2: float = 0.20
    w3: float = 0.15
    w4: float = 0.20
    w5: float = 0.15
    w6: float = 0.10
    # Psweep
    a1: float = 0.02
    a2: float = 0.22
    a3: float = 0.22
    a4: float = 0.15
    a5: float = 0.20
    # Ptrend
    b1: float = 0.90
    b2: float = 0.35
    b3: float = 0.30
    b4: float = 0.22
    # Acceptance
    c1: float = 0.25
    c2: float = 0.22
    c3: float = 0.25
    c4: float = 0.20
    c5: float = 0.18
class LiquidityWormEngine:
    round_step_bps: float = 25.0

    def analyze(
        self,
        market: Dict[str, Any],
        spoof: Dict[str, Any],
        macro: Dict[str, Any],
        regime: Dict[str, Any],
    ) -> Dict[str, Any]:
        symbol = str(market.get("primary_symbol", "")).replace("/", "").replace(":", "")

        net_pct = float(market.get("net_pct", 0.0) or 0.0)
        spread_map = market.get("per_leg_spread_bps", {}) or {}
        mean_spread_bps = sum(float(v or 0.0) for v in spread_map.values()) / max(1, len(spread_map))
        quote_volume = float(market.get("quote_volume_total", 0.0) or 0.0)

        atr_pct = float((((macro.get("atr") or {}).get("pct", 0.0)) or 0.0))
        funding_rate = float((((macro.get("funding") or {}).get("funding_rate", 0.0)) or 0.0))
        oi_delta = float((((macro.get("open_interest") or {}).get("oi_delta", 0.0)) or 0.0))
        basis = float((((macro.get("long_short_ratio") or {}).get("ratio", 1.0)) or 1.0)) - 1.0

        imbalance = float(spoof.get("orderbook_imbalance", 0.0) or 0.0)
        ghost_count = int(spoof.get("ghost_walls_detected", 0) or 0)
        iceberg = bool(spoof.get("iceberg_detected", False))

        # A) Liquidity map pieces
        # A) Liquidity map
        d_pdh_pdl = abs(net_pct)
        d_pwh_pwl = abs(mean_spread_bps / 100.0)
        d_round = abs((mean_spread_bps % self.round_step_bps) / self.round_step_bps)
        d_swing = min(1.0, atr_pct / 10.0)
        rejection_density = min(1.0, abs(imbalance) * 1.8)
        liq_cluster = min(1.0, quote_volume / 4_000_000)

        pd_level = 1.0 - min(1.0, d_pdh_pdl)
        pw_level = 1.0 - min(1.0, d_pwh_pwl)
        round_level = 1.0 - min(1.0, d_round)
        range_edge = 1.0 - min(1.0, d_swing)

        liquidity_score_norm = max(
            0.0,
            min(
                1.0,
                self.w1 * pd_level
                + self.w2 * pw_level
                + self.w3 * round_level
                + self.w4 * range_edge
                + self.w5 * rejection_density
                + self.w6 * liq_cluster,
            ),
        )
        liquidity_proximity_score = self._clip100(liquidity_score_norm * 100.0)

        # B) WVI split + crowding stress
        funding_z = min(4.0, abs(funding_rate) / 0.0004)
        volume_impulse = min(4.0, quote_volume / 1_500_000)
        spot_followthrough = max(0.0, min(4.0, (abs(net_pct) / max(0.15, atr_pct * 0.25))))
        liquidity_proximity_score = self._clip100(100.0 - (d_pdh_pdl * 20 + d_pwh_pwl * 20 + d_round * 20 + d_swing * 40))

        # B) WVI split + crowding stress
        funding_z = min(4.0, abs(funding_rate) / 0.0004)
        price_delta = abs(net_pct)
        realized_vol = atr_pct
        volume_impulse = min(4.0, quote_volume / 1_500_000)
        spot_followthrough = max(0.0, min(4.0, (price_delta / max(0.15, atr_pct * 0.25))))

        wvi_crowding = funding_z + min(4.0, abs(oi_delta))
        wvi_instability = volume_impulse - spot_followthrough
        wvi = wvi_crowding + wvi_instability

        crowding_score = self._clip100(wvi_crowding * 15 + abs(oi_delta) * 18 + abs(basis) * 35)
        squeeze_risk_score = self._clip100(crowding_score * 0.65 + abs(imbalance) * 35 + max(0.0, wvi_instability) * 12)

        # C) Sweep detector
        wick_through = mean_spread_bps > 12
        close_inside = abs(net_pct) < 0.18
        volume_spike = quote_volume > 2_000_000
        delta_oi_anomaly = abs(oi_delta) > 1.5
        time_to_reclaim = max(0.0, 1.0 - abs(net_pct) * 0.5)
        reclaim_strength = max(0.0, min(1.0, time_to_reclaim * 0.55 + (0.25 if volume_spike else 0.0) + (0.2 if close_inside else 0.0)))

        sweep_detected = bool(wick_through and close_inside and (volume_spike or delta_oi_anomaly))
        sweep_direction = "up_sweep" if imbalance < 0 else "down_sweep" if imbalance > 0 else "none"

        failed_break_count = int(wick_through) + int(close_inside)
        extreme_funding = 1.0 if funding_z >= 2.4 else 0.0
        oi_acceleration = min(1.0, abs(oi_delta) / 3.0)

        # D) Break validation + acceptance
        close_beyond_level = abs(net_pct) > 0.20
        retest_hold = 0.12 < abs(net_pct) < 0.55
        oi_behavior_ok = crowding_score < 68
        spot_perp_alignment = str(regime.get("regime", "")).upper() in {"CONVERGENCE", "TREND"}
        volume_confirmation = quote_volume > 900_000

        break_hold_retest_score = (
            0.35 * float(close_beyond_level)
            + 0.35 * float(retest_hold)
            + 0.30 * float(volume_confirmation)
        )

        acceptance_score = max(
            0.0,
            min(
                1.0,
                self.c1 * time_to_reclaim
                + self.c2 * float(close_beyond_level)
                + self.c3 * float(retest_hold)
                + self.c4 * float(spot_perp_alignment)
                - self.c5 * min(1.0, wvi / 8.0),
                0.22 * close_beyond_level
                + 0.26 * retest_hold
                + 0.22 * volume_confirmation
                + 0.22 * spot_perp_alignment
                + 0.08 * oi_behavior_ok
                - 0.18 * (wvi > 4.0),
            ),
        )

        true_break_prob = max(0.0, min(1.0, acceptance_score + (0.08 if oi_behavior_ok else -0.05)))
        failure_break_prob = max(0.0, min(1.0, 1.0 - true_break_prob + (0.12 if crowding_score > 75 else 0.0)))

        # Probabilistic heads
        p_sweep = self._sigmoid(
            self.a1 * liquidity_proximity_score
            + self.a2 * wvi
            + self.a3 * failed_break_count
            + self.a4 * extreme_funding
            + self.a5 * oi_acceleration
            - 2.4
        )

        p_trend = self._sigmoid(
            self.b1 * break_hold_retest_score
            + self.b2 * float(spot_perp_alignment)
            + self.b3 * float(volume_confirmation)
            - self.b4 * max(0.0, wvi)
            - 0.3
        # Probabilistic regime heads
        p_sweep = self._sigmoid(
            0.02 * liquidity_proximity_score
            + 0.22 * wvi_crowding
            + 0.18 * max(0.0, wvi_instability)
            + 0.25 * (1.0 if sweep_detected else 0.0)
            + 0.18 * (1.0 if close_inside else 0.0)
            - 2.1
        )
        p_trend = self._sigmoid(
            0.9 * acceptance_score
            + 0.35 * (1.0 if volume_confirmation else 0.0)
            + 0.25 * (1.0 if spot_perp_alignment else 0.0)
            - 0.22 * max(0.0, wvi_instability)
            - 0.3 * (1.0 if crowding_score > 80 else 0.0)
            - 0.35
        )

        # E) Book integrity / spoof
        wall_persistence = max(0.0, min(1.0, ghost_count / 4.0))
        cancel_velocity = max(0.0, min(1.0, abs(imbalance) * 1.5 + (0.3 if iceberg else 0.0)))
        depth_stability = max(0.0, min(1.0, 1.0 - (mean_spread_bps / 35.0)))
        imbalance_change = abs(imbalance)
        fake_sr_prob = max(0.0, min(1.0, cancel_velocity * 0.5 + (1.0 - depth_stability) * 0.3 + wall_persistence * 0.2))
        spoof_risk = self._clip100(fake_sr_prob * 100.0)
        wall_quality_score = self._clip100((wall_persistence * 40 + depth_stability * 40 + (1.0 - cancel_velocity) * 20))

        regime_label, trigger = self._classify_regime(
            p_sweep=p_sweep,
            p_trend=p_trend,
            reclaim_strength=reclaim_strength,
            acceptance_score=acceptance_score,
        )

        return {
            "symbol": symbol,
            "liquidity_map": {
                "distance_to_pdh_pdl": round(d_pdh_pdl, 4),
                "distance_to_pwh_pwl": round(d_pwh_pwl, 4),
                "distance_to_round_number": round(d_round, 4),
                "distance_to_recent_swing": round(d_swing, 4),
                "rejection_density": round(rejection_density, 4),
                "liquidity_cluster": round(liq_cluster, 4),
                "liquidity_score": round(liquidity_score_norm, 4),
                "liquidity_proximity_score": round(liquidity_proximity_score, 2),
            },
            "crowding_stress": {
                "oi_delta": round(oi_delta, 4),
                "funding_zscore": round(funding_z, 4),
                "price_delta": round(abs(net_pct), 4),
                "realized_vol": round(atr_pct, 4),
                "price_delta": round(price_delta, 4),
                "realized_vol": round(realized_vol, 4),
                "basis_perp_premium": round(basis, 6),
                "wvi_crowding": round(wvi_crowding, 4),
                "wvi_instability": round(wvi_instability, 4),
                "wvi": round(wvi, 4),
                "crowding_score": round(crowding_score, 2),
                "squeeze_risk_score": round(squeeze_risk_score, 2),
            },
            "sweep_detector": {
                "wick_through_key_level": wick_through,
                "close_back_inside_range": close_inside,
                "volume_spike": volume_spike,
                "delta_oi_anomaly": delta_oi_anomaly,
                "time_to_reclaim": round(time_to_reclaim, 4),
                "failed_break_count": failed_break_count,
                "sweep_detected": sweep_detected,
                "sweep_direction": sweep_direction,
                "reclaim_strength": round(reclaim_strength, 4),
            },
            "break_validation": {
                "close_beyond_level": close_beyond_level,
                "retest_hold": retest_hold,
                "oi_behavior_ok": oi_behavior_ok,
                "spot_perp_alignment": spot_perp_alignment,
                "volume_confirmation": volume_confirmation,
                "break_hold_retest_score": round(break_hold_retest_score, 4),
                "acceptance_score": round(acceptance_score, 4),
                "true_break_prob": round(true_break_prob, 4),
                "failure_break_prob": round(failure_break_prob, 4),
            },
            "book_integrity": {
                "wall_persistence": round(wall_persistence, 4),
                "cancel_velocity": round(cancel_velocity, 4),
                "depth_stability": round(depth_stability, 4),
                "imbalance_change_near_price": round(imbalance_change, 4),
                "fake_support_resistance_probability": round(fake_sr_prob, 4),
                "spoof_risk": round(spoof_risk, 2),
                "wall_quality_score": round(wall_quality_score, 2),
            },
            "probabilities": {
                "p_sweep": round(p_sweep, 4),
                "p_trend": round(p_trend, 4),
                "p_neutral": round(max(0.0, min(1.0, 1.0 - max(p_sweep, p_trend))), 4),
            },
            "regime": regime_label,
            "trigger": trigger,
            "labels": self._labels(regime_label, squeeze_risk_score),
            "notes": self._notes(
                crowding_score=crowding_score,
                squeeze_risk_score=squeeze_risk_score,
                sweep_detected=sweep_detected,
                true_break_prob=true_break_prob,
                acceptance_score=acceptance_score,
            ),
        }

    def _classify_regime(
        self,
        *,
        p_sweep: float,
        p_trend: float,
        reclaim_strength: float,
        acceptance_score: float,
    ) -> tuple[str, str]:
        if p_sweep > 0.62 and reclaim_strength > 0.45:
            return "sweep_reversal", "sweep_and_reclaim"
        if p_trend > 0.62 and acceptance_score > 0.55:
            return "trend_continuation", "break_hold_retest"
        return "neutral_transition", "wait"

    def _labels(self, regime_label: str, squeeze_risk_score: float) -> List[str]:
        out = [regime_label]
        if regime_label == "sweep_reversal":
            out.append("false_break_sweep_reversal_candidate")
        if regime_label == "trend_continuation":
            out.append("true_breakout_continuation_candidate")
        if squeeze_risk_score >= 70:
            out.append("squeeze_risk_elevated")
        return out

    def _notes(
        self,
        *,
        crowding_score: float,
        squeeze_risk_score: float,
        sweep_detected: bool,
        true_break_prob: float,
        acceptance_score: float,
    ) -> List[str]:
        notes: List[str] = []
        if crowding_score > 70:
            notes.append("high_crowding")
        if squeeze_risk_score > 75:
            notes.append("squeeze_probability_rising")
        if sweep_detected:
            notes.append("liquidity_grab_signature")
        if true_break_prob > 0.65 and acceptance_score > 0.55:
            notes.append("clean_break_acceptance")
        if not notes:
            notes.append("mixed_structure")
        return notes

    def _clip100(self, v: float) -> float:
        return max(0.0, min(100.0, v))

    def _sigmoid(self, x: float) -> float:
        return 1.0 / (1.0 + math.exp(-max(-30.0, min(30.0, x))))


# Backward compatibility alias
LiquidityWormEngine = LiquidityWormService
liquidity_worm = LiquidityWormService()
        # stable enough range for this module
        if x >= 0:
            z = 1.0 / (1.0 + (2.718281828 ** (-x)))
        else:
            ex = 2.718281828 ** x
            z = ex / (1.0 + ex)
        return max(0.0, min(1.0, z))


liquidity_worm = LiquidityWormEngine()
