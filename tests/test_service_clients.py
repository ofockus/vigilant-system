import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from core.service_clients import ServiceClients


class FakeResponse:
    def __init__(self, payload, ok=True):
        self._payload = payload
        self._ok = ok

    def raise_for_status(self):
        if not self._ok:
            raise RuntimeError("bad")

    def json(self):
        return self._payload


@pytest.mark.asyncio
async def test_service_clients_schema_validate(monkeypatch):
    sc = ServiceClients()
    sc.endpoints["spoofhunter"] = "http://example"

    async def fake_request(*args, **kwargs):
        return FakeResponse({"symbol": "BTCUSDT", "ghost_count": 2, "confidence": 0.8})

    monkeypatch.setattr(sc._client, "request", fake_request)
    data = await sc.get_spoof_state("BTC/USDT")
    assert data["symbol"] == "BTCUSDT"
    assert data["ghost_count"] == 2


@pytest.mark.asyncio
async def test_service_clients_retry_failure(monkeypatch):
    sc = ServiceClients()
    sc.endpoints["spoofhunter"] = "http://example"

    async def bad_request(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(sc._client, "request", bad_request)
    data = await sc.get_spoof_state("BTC/USDT")
    assert data is None
