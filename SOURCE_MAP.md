# Source map

- **main.py + config/core/executors/scanners/utils** ← `apex-v666-main.zip` — Primary engine/runtime
- **services/*.py + apex_common/* + tests/v3/* + examples/*** ← `apex-citadel-v3-complete(2).tar.gz` — Specialized intelligence/risk nodes
- **web/*** ← `thisisapex-main(2).zip` — Dashboard/app shell and Binance helper endpoints
- **infra/scripts/* + infra/legacy/master_orchestrator.py** ← `apexcitadelehfoda-main.zip` — Bootstrap, readiness, and ops scripts
- **docs/source/DEPLOY*.md + some duplicate engine files** ← `nothingbreakslikeahearth-main.zip` — Secondary reference / cross-check
- **legacy/prototypes/* + docs/openclaw_assets/*** ← `earlier local uploads` — Pitch/demo/history and contest-facing assets

## Merge policy

- Prefer `apex-v666` for runtime-critical files.
- Prefer `apex-v3` for optional intelligence nodes and tests.
- Keep `thisisapex` inside `web/` instead of mixing Node and Python roots.
- Keep old prototypes under `legacy/` so ideas are preserved without polluting runtime imports.
