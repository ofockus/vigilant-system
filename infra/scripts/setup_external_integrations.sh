#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
THIRD_PARTY_DIR="$ROOT_DIR/third_party"
mkdir -p "$THIRD_PARTY_DIR"

clone_or_update() {
  local name="$1"
  local repo="$2"
  local path="$THIRD_PARTY_DIR/$name"

  if [[ -d "$path/.git" ]]; then
    echo "[update] $name"
    git -C "$path" pull --ff-only
  else
    echo "[clone] $name"
    git clone --depth 1 "$repo" "$path"
  fi
}

clone_or_update "cli-anything" "https://github.com/HKUDS/CLI-Anything"
clone_or_update "bitnet" "https://github.com/microsoft/BitNet"
clone_or_update "nanochat" "https://github.com/karpathy/nanochat"
clone_or_update "openclaw" "https://github.com/openclaw/openclaw"
clone_or_update "page-agent" "https://github.com/alibaba/page-agent"
clone_or_update "hermes-agent" "https://github.com/NousResearch/hermes-agent"

echo "[ok] external integrations ready in $THIRD_PARTY_DIR"
echo "[next] test local gateway: uvicorn services.openclaw_gateway:app --host 0.0.0.0 --port 8090"
