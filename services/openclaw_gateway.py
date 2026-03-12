from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI

from core.external_integrations import ExternalIntegrationRegistry


ROOT = Path(__file__).resolve().parents[1]
registry = ExternalIntegrationRegistry(str(ROOT))
app = FastAPI(title="OpenClaw Integration Gateway", version="1.0.0")


@app.get("/health")
async def health() -> dict:
    return {"ok": True, "service": "openclaw-gateway"}


@app.get("/integrations/status")
async def integrations_status() -> dict:
    return {"ok": True, "integrations": registry.status()}
