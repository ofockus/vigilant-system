from __future__ import annotations

from typing import Any, Dict, Optional

from pydantic import BaseModel, Field


class ServiceEnvelope(BaseModel):
    ok: bool = True
    source: Optional[str] = None


class SpoofState(BaseModel):
    symbol: str = ""
    ghost_count: int = 0
    confidence: float = 0.0


class RegimeState(BaseModel):
    symbol: str = ""
    regime: str = "NEUTRAL"
    confidence: float = 0.0


class NarrativeState(BaseModel):
    symbol: str = ""
    sentiment: str = "NEUTRAL"
    score: float = 0.0


class MacroState(BaseModel):
    symbol: str = ""
    funding_rate: float = 0.0
    atr_pct: float = 0.0


class TokenRiskState(BaseModel):
    rug_risk_pct: float = Field(default=0.0, ge=0.0)
    flags: Dict[str, Any] = Field(default_factory=dict)
