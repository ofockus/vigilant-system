from __future__ import annotations

import asyncio
import random
from abc import ABC, abstractmethod
from typing import Any, Dict

from config.config import cfg


class NodeBase(ABC):
    name: str = "node"

    async def run_with_jitter(self, payload: Dict[str, Any], base_delay_s: float = 0.01) -> Dict[str, Any]:
        await asyncio.sleep(base_delay_s * random.uniform(cfg.REQUEST_JITTER_MIN, cfg.REQUEST_JITTER_MAX))
        return await self.run(payload)

    @abstractmethod
    async def run(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        raise NotImplementedError
