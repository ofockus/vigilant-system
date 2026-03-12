import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.external_integrations import ExternalIntegrationRegistry


def test_registry_status(tmp_path):
    reg = ExternalIntegrationRegistry(str(tmp_path))
    status = reg.status()
    assert "openclaw" in status
    assert "page-agent" in status
    assert "hermes-agent" in status
    assert status["openclaw"]["installed"] is False
