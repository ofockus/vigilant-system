#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/../.."

if [[ ! -f .env ]]; then
  cp .env.example .env
  echo "[info] .env created from .env.example"
fi

if [[ -x infra/scripts/setup_external_integrations.sh ]]; then
  infra/scripts/setup_external_integrations.sh
fi

docker compose up -d redis spoofhunter antirug newtonian narrative econopredator openclaw_gateway scanner singapore_executor tokyo_executor

echo "[ok] FastAPI nodes and core runtime started"
docker compose ps
