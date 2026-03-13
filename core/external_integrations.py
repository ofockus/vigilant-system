from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List


@dataclass(frozen=True)
class IntegrationSpec:
    name: str
    repo: str
    path: str


INTEGRATIONS: List[IntegrationSpec] = [
    IntegrationSpec("cli-anything", "https://github.com/HKUDS/CLI-Anything", "third_party/cli-anything"),
    IntegrationSpec("bitnet", "https://github.com/microsoft/BitNet", "third_party/bitnet"),
    IntegrationSpec("nanochat", "https://github.com/karpathy/nanochat", "third_party/nanochat"),
    IntegrationSpec("openclaw", "https://github.com/openclaw/openclaw", "third_party/openclaw"),
    IntegrationSpec("page-agent", "https://github.com/alibaba/page-agent", "third_party/page-agent"),
    IntegrationSpec("hermes-agent", "https://github.com/NousResearch/hermes-agent", "third_party/hermes-agent"),
]


class ExternalIntegrationRegistry:
    def __init__(self, root_dir: str = ".") -> None:
        self.root_dir = Path(root_dir)

    def status(self) -> Dict[str, Dict[str, str | bool]]:
        out: Dict[str, Dict[str, str | bool]] = {}
        for spec in INTEGRATIONS:
            p = self.root_dir / spec.path
            out[spec.name] = {
                "repo": spec.repo,
                "path": str(p),
                "installed": p.exists(),
                "git_dir": (p / ".git").exists(),
            }
        return out
