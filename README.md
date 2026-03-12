# Apex OpenClaw Fusion Skeleton

This repository is a consolidation skeleton built from multiple internal Apex lineages.

## What is included

- **Trading engine** from the v666 branch:
  - `main.py`
  - `config/`
  - `core/`
  - `executors/`
  - `scanners/`
  - `utils/`
- **Optional intelligence/risk nodes** from the v3 lineage:
  - `services/spoofhunter.py`
  - `services/antirug_v3.py`
  - `services/newtonian.py`
  - `services/econopredator.py`
  - `services/narrative.py`
  - `services/dreamer.py`
  - `services/maestro_v3.py`
  - `services/backtester.py`
- **Shared helpers**:
  - `apex_common/`
  - `core/service_clients.py`
  - `core/fusion_registry.py`
- **Contest-facing app shell**:
  - `web/`
- **Infra/ops scripts**:
  - `infra/scripts/`
- **References and legacy**:
  - `docs/`
  - `legacy/`

## Directory layout

```txt
.
├── apex_common/          # shared utilities used by v3 services
├── config/               # engine config
├── core/                 # engine core + new fusion hooks
├── executors/            # Singapore/Tokyo executor flow
├── scanners/             # triangular scanner
├── services/             # optional FastAPI nodes
├── tests/                # imported tests
├── utils/                # redis/pubsub
├── web/                  # Node/Vite dashboard + helper API
├── infra/                # setup/readiness scripts
├── docs/                 # deploy notes and contest assets
└── legacy/               # old prototypes kept for reference
```

## Suggested first pass

1. Install Python deps from `requirements.fusion.txt`.
2. Copy `.env.fusion.example` to `.env`.
3. Start Redis.
4. Boot the engine with `python main.py` using `APEX_ROLE=scanner`.
5. Boot optional services with `python -m services.<name>`.
6. Boot the web app from `web/`.

### One-command Pop!_OS bootstrap

Run `infra/scripts/install_and_run_popos.sh` to install system deps, create `.venv`, generate `.env` template, start Redis, and launch `main.py` in background.


## What is deliberately *not* merged yet

- Direct hard-coupling between the scanner and all v3 services.
- Automatic execution on live keys.
- Any unsafe “god mode” branding in the runtime path.

The current skeleton is meant to be a clean consolidation point, not a claim that every imported module already inter-operates perfectly.

## Agent skill-stack guidance

For a security-first list of recommended agent skill categories, rollout order, and operational safeguards, see `docs/source/AGENT_SKILL_STACK_GUIDE.md`.

## Skills added

- `skills/openclaw/SKILL.md`: translates fusion output into deterministic OpenClaw actions (`execute`, `watch`, `block`).
- `skills/binance/SKILL.md`: normalizes Binance market context into a stable payload contract.
- `skills/openclaw-binance/SKILL.md`: bridge contract that combines both skills into one handoff object.
- Runtime integration lives in `core/skill_bridge.py` and is attached to `FusionRegistry` as `skill_handoff`.


## AdversarialShield (safe mode)

- Module: `core/adversarial_shield.py`
- Example integration: `examples/apex_predator_neo.py`
- Unit tests: `tests/test_adversarial_shield.py`

Safety behavior:
- Decoy/spoof behavior is intentionally disabled.
- Use only testnet/sandbox credentials and small order sizes for validation.

### Test without risking a real account

1. Use Binance testnet API keys in `.env` (`TESTNET=True`).
2. Run unit tests first: `pytest -q tests/test_adversarial_shield.py`.
3. Run the local integration example with mocked exchange class: `python examples/apex_predator_neo.py`.
4. If integrating with real exchange clients, keep strict max capital and circuit breaker enabled.


## Refactor 2026: Resilience + Performance

- `core/service_clients.py`: retries (3x), backoff exponencial + jitter, schema validation (Pydantic), shared `httpx.AsyncClient`.
- `scanners/dynamic_tri_scanner.py`: parallel orderbook fetch with `asyncio.gather`, jittered cycle sleep, narrative sniping boost heuristic.
- `core/adversarial_shield.py`: defensive jitter defaults `0.6..1.2`, bounded retries, IOC execution path, circuit breaker hooks.
- `core/backtester_simple.py`: tick-level replay backtester for smoke validation.
- `core/node_base.py`: async base class with jittered execution helper for node specialization.

### Run

Python local:
- `python main.py`

Docker compose:
- `docker compose up --build`

### OpenClaw integration next steps (FastAPI)

1. Expose `POST /v1/fusion/evaluate` wrapping `fusion_registry.evaluate_opportunity`.
2. Expose `POST /v1/risk/check` returning `robin_hood.summary()` and allow/deny status.
3. Expose `POST /v1/backtest/replay` using `SimpleTickBacktester`.
4. Expose `GET /v1/health/services` using `service_clients.health()`.


## Binance Skills Hub (all skills)

Installed set from `github.com/binance/binance-skills-hub`:
- query-address-info
- meme-rush
- trading-signal
- query-token-audit
- crypto-market-rank
- query-token-info
- derivatives-trading-usds-futures
- square-post
- assets
- margin-trading
- spot
- alpha

Use script:
- `infra/scripts/install_binance_skills.sh`

After installation: **Restart Codex to pick up new skills.**

## FastAPI nodes activated

`docker-compose.yml` now includes always-on services:
- `spoofhunter` (`:8011`)
- `antirug` (`:8012`)
- `newtonian` (`:8013`)
- `narrative` (`:8014`)
- `econopredator` (`:8015`)

Scanner receives service URLs via environment variables and can consume them through `core/service_clients.py`.

Quick start:
- `cp .env.example .env`
- `infra/scripts/activate_fastapi_nodes.sh`


## External AI stack integration (CLI-Anything + BitNet + nanochat + OpenClaw + Page-Agent + Hermes-Agent)

This project now supports local-first integration of:
- `HKUDS/CLI-Anything`
- `microsoft/BitNet`
- `karpathy/nanochat`
- `openclaw/openclaw`
- `alibaba/page-agent`
- `NousResearch/hermes-agent`

### Local bootstrap

1. Clone/update external repos:
   - `infra/scripts/setup_external_integrations.sh`
2. Start full stack (including gateway + FastAPI services):
   - `infra/scripts/activate_fastapi_nodes.sh`

### Browser testing

After startup, open:
- `http://localhost:8090/docs` (OpenClaw Integration Gateway Swagger)
- `http://localhost:8090/integrations/status` (installed status for each external repo)

The gateway lives at `services/openclaw_gateway.py` and reads integration status from `core/external_integrations.py`.


## Liquidity Worm module (5 measurable blocks)

Module: `services/liquidity_worm.py`

- A. Liquidity Map → `liquidity_proximity_score`
- B. Crowding Stress → `crowding_score`, `squeeze_risk_score`
- C. Sweep Detector → `sweep_detected`, `sweep_direction`, `reclaim_strength`
- D. Break Validation → `true_break_prob`, `failure_break_prob`, `acceptance_score`
- E. Book Integrity / Spoof Layer → `spoof_risk`, `wall_quality_score`

Also outputs:
- `wvi_crowding`, `wvi_instability`, `wvi`
- probabilistic heads: `p_sweep`, `p_trend`, `p_neutral`
- classification: `regime` + `trigger` (`sweep_and_reclaim`, `break_hold_retest`, `wait`)

Integration:
- `core/fusion_registry.py` computes `envelope.liquidity` and uses probabilities + acceptance for boost/penalty/veto in final decisioning.


### Example Liquidity Worm JSON output

```json
{
  "symbol": "ETHUSDT",
  "liquidity_map": {
    "liquidity_proximity_score": 78.4
  },
  "crowding_stress": {
    "wvi": 5.12,
    "crowding_score": 73.8,
    "squeeze_risk_score": 69.2
  },
  "sweep_detector": {
    "sweep_detected": true,
    "sweep_direction": "up_sweep",
    "reclaim_strength": 0.62
  },
  "break_validation": {
    "acceptance_score": 0.41,
    "true_break_prob": 0.44,
    "failure_break_prob": 0.68
  },
  "book_integrity": {
    "spoof_risk": 58.7,
    "wall_quality_score": 47.5
  },
  "probabilities": {
    "p_sweep": 0.74,
    "p_trend": 0.29,
    "p_neutral": 0.26
  },
  "regime": "sweep_reversal",
  "trigger": "sweep_and_reclaim"
}
```

### Scan loop integration (Apex)

In `scanners/dynamic_tri_scanner.py`, the scan cycle now consumes `fusion.liquidity.crowding_stress.wvi` and triggers Robin Hood pause when WVI is above `WVI_PAUSE_THRESHOLD`.

For custom runners like `apex_predator_neo.py`, use the same pattern:

```python
wvi = float((((fusion_payload.get("liquidity") or {}).get("crowding_stress") or {}).get("wvi", 0.0) or 0.0)
if wvi >= cfg.WVI_PAUSE_THRESHOLD:
    await robin_hood.trigger_pause(f"WVI {wvi:.2f} acima do limite")
```


### Conflict resolution check

Use `infra/scripts/resolve_conflicts.sh` before commits/PRs to fail fast if any merge conflict marker (`<<<<<<<`, `=======`, `>>>>>>>`) remains in tracked source paths.


### AdversarialShieldWorm integration

New class: `core/adversarial_shield.py::AdversarialShieldWorm`

Capabilities (defensive):
- spoof risk detection (`wall_persistence` + low `acceptance_score`)
- fake sweep detection (`p_sweep` + reclaim strength)
- adaptive jitter from `wvi_instability`
- IOC defensive execution when sweep risk is high
- subaccount alias rotation simulation when `wvi_crowding` is extreme
- circuit-breaker recommendation from regime + WVI

Usage:
```python
from core.adversarial_shield import AdversarialShieldWorm

shield = AdversarialShieldWorm(exchange)
worm = shield.evaluate_market_state(market, spoof, macro, regime)
if shield.maybe_trip_circuit_breaker(worm):
    ...
```
