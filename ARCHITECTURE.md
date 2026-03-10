# Architecture

```txt
Binance Spot/Testnet
     │
     ├── core/binance_connector.py
     │
     ├── scanners/dynamic_tri_scanner.py
     │         │
     │         └── core/confluence_engine.py
     │
     ├── utils/redis_pubsub.py
     │         │
     │         ├── executors/singapore_executor.py
     │         └── executors/tokyo_executor.py
     │
     └── core/fusion_registry.py
               │
               ├── services/spoofhunter.py
               ├── services/antirug_v3.py
               ├── services/newtonian.py
               ├── services/narrative.py
               ├── services/econopredator.py
               ├── services/dreamer.py
               └── services/maestro_v3.py

web/server.ts + web/src/*
     │
     └── dashboard / contest demo shell
```
