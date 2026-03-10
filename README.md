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

## What is deliberately *not* merged yet

- Direct hard-coupling between the scanner and all v3 services.
- Automatic execution on live keys.
- Any unsafe “god mode” branding in the runtime path.

The current skeleton is meant to be a clean consolidation point, not a claim that every imported module already inter-operates perfectly.
