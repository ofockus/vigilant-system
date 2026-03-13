import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from core.robin_hood_risk import robin_hood


@pytest.mark.asyncio
async def test_trigger_pause_sets_state(monkeypatch):
    async def _noop(*_args, **_kwargs):
        return True

    monkeypatch.setattr("core.robin_hood_risk.redis_bus.publish", _noop)
    monkeypatch.setattr("core.robin_hood_risk.redis_bus.set_state", _noop)

    robin_hood.state.paused = False
    robin_hood.state.pause_reason = ""
    await robin_hood.trigger_pause("test_wvi")

    assert robin_hood.state.paused is True
    assert robin_hood.state.pause_reason == "test_wvi"
