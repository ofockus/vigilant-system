"""HTTP clients for optional v3 FastAPI nodes with retries, jitter and schema validation."""
from __future__ import annotations

import asyncio
import random
from typing import Any, Dict, Optional

import httpx
from loguru import logger
from pydantic import ValidationError

from config.config import cfg
from core.schemas import MacroState, NarrativeState, RegimeState, SpoofState, TokenRiskState


class ServiceClients:
    def __init__(self) -> None:
        self.endpoints = {
            "spoofhunter": cfg.SPOOFHUNTER_URL,
            "antirug": cfg.ANTIRUG_URL,
            "newtonian": cfg.NEWTONIAN_URL,
            "narrative": cfg.NARRATIVE_URL,
            "econopredator": cfg.ECONOPREDATOR_URL,
        }
        self._client = httpx.AsyncClient(timeout=3.0)

    def enabled(self, service: str) -> bool:
        return cfg.FUSION_USE_REMOTE_SERVICES and bool(self.endpoints.get(service))

    async def close(self) -> None:
        await self._client.aclose()

    async def _request_json(
        self,
        service: str,
        method: str,
        path: str,
        json: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        base = (self.endpoints.get(service) or "").rstrip("/")
        if not base:
            return None

        url = f"{base}/{path.lstrip('/')}"
        last_exc: Optional[Exception] = None

        for attempt in range(1, cfg.RETRY_ATTEMPTS + 1):
            try:
                resp = await self._client.request(method.upper(), url, json=json)
                resp.raise_for_status()
                data = resp.json()
                if not isinstance(data, dict):
                    raise ValueError("response_not_object")
                return data
            except Exception as exc:
                last_exc = exc
                backoff = (2 ** (attempt - 1)) * 0.2 * random.uniform(cfg.REQUEST_JITTER_MIN, cfg.REQUEST_JITTER_MAX)
                logger.debug(
                    "service_call_retry service={} attempt={} backoff_ms={} err={}",
                    service,
                    attempt,
                    int(backoff * 1000),
                    type(exc).__name__,
                )
                await asyncio.sleep(backoff)

        logger.warning("service_call_failed service={} path={} err={}", service, path, type(last_exc).__name__ if last_exc else "unknown")
        return None

    def _validate(self, model: Any, payload: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        if payload is None:
            return None
        try:
            return model.model_validate(payload).model_dump()
        except ValidationError as exc:
            logger.debug("schema_validation_failed model={} err={}", model.__name__, exc.__class__.__name__)
            return payload

    async def get_health(self, service: str) -> Optional[Dict[str, Any]]:
        return await self._request_json(service, "GET", "/health")

    async def get_spoof_state(self, symbol: str) -> Optional[Dict[str, Any]]:
        clean = symbol.replace("/", "").replace(":", "")
        data = await self._request_json("spoofhunter", "GET", f"/spoof_state/{clean}")
        return self._validate(SpoofState, data)

    async def get_regime_state(self, asset: str) -> Optional[Dict[str, Any]]:
        clean = asset.replace("/", "").replace(":", "")
        data = await self._request_json("newtonian", "GET", f"/gravity_state/{clean}")
        return self._validate(RegimeState, data)

    async def get_narrative_state(self, symbol_or_asset: str) -> Optional[Dict[str, Any]]:
        clean = symbol_or_asset.replace("/", "").replace(":", "")
        data = await self._request_json("narrative", "GET", f"/sentiment_state/{clean}")
        return self._validate(NarrativeState, data)

    async def get_macro_state(self, symbol: str) -> Optional[Dict[str, Any]]:
        clean = symbol.replace("/", "").replace(":", "")
        data = await self._request_json("econopredator", "GET", f"/market_data/{clean}")
        return self._validate(MacroState, data)

    async def analyze_token(self, metrics: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        data = await self._request_json("antirug", "POST", "/analyze_token_v2", json=metrics)
        return self._validate(TokenRiskState, data)

    async def health(self) -> Dict[str, Any]:
        data: Dict[str, Any] = {}
        for name in self.endpoints:
            try:
                data[name] = await self.get_health(name)
            except Exception as exc:
                data[name] = {"ok": False, "error": type(exc).__name__}
        return data


service_clients = ServiceClients()
