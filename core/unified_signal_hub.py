"""Unified orchestration for fusion + worm-defense + skill handoff."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional

from core.adversarial_shield import AdversarialShieldWorm
from core.fusion_registry import FusionRegistry


@dataclass
class UnifiedCycleResult:
    envelope: Dict[str, Any]
    decision: Dict[str, Any]
    mitigation: Dict[str, Any]
    actions: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "envelope": self.envelope,
            "decision": self.decision,
            "mitigation": self.mitigation,
            "actions": self.actions,
        }


class UnifiedSignalHub:
    """Single-cycle async orchestrator for fusion + defensive shield."""

    def __init__(self, fusion_registry: FusionRegistry, shield: AdversarialShieldWorm) -> None:
        self.fusion_registry = fusion_registry
        self.shield = shield

    async def run_cycle(
        self,
        *,
        opportunity: Dict[str, Any],
        confluence_result: Any,
        orderbooks: Dict[str, Dict[str, Any]],
        tickers: Dict[str, Dict[str, Any]],
        markets: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> UnifiedCycleResult:
        envelope_obj = await self.fusion_registry.evaluate_opportunity(
            opportunity=opportunity,
            confluence_result=confluence_result,
            orderbooks=orderbooks,
            tickers=tickers,
            markets=markets,
        )
        envelope = envelope_obj.to_dict()

        worm_output = self.shield.evaluate_market_state(
            market=envelope_obj.market,
            spoof=envelope_obj.spoof,
            macro=envelope_obj.macro,
            regime=envelope_obj.regime,
        )
        mitigation = worm_output.get("mitigation", {})

        actions = {
            "pause_recommended": bool(mitigation.get("pause_recommended", False)),
            "rotate_subaccount_alias": self.shield.maybe_rotate_subaccount(worm_output),
            "ghost_execution_mode": bool(mitigation.get("ghost_execution_mode", False)),
            "circuit_breaker_tripped": self.shield.maybe_trip_circuit_breaker(worm_output),
        }

        return UnifiedCycleResult(
            envelope=envelope,
            decision=envelope_obj.decision,
            mitigation=mitigation,
            actions=actions,
        )
