import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient

from services.openclaw_gateway import app


def test_gateway_health():
    client = TestClient(app)
    data = client.get('/health').json()
    assert data['ok'] is True


def test_gateway_integrations_status():
    client = TestClient(app)
    data = client.get('/integrations/status').json()
    assert data['ok'] is True
    assert 'integrations' in data
    assert 'openclaw' in data['integrations']
    assert 'page-agent' in data['integrations']
    assert 'hermes-agent' in data['integrations']
