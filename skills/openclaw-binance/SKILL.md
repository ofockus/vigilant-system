---
name: openclaw-binance-bridge
description: Compose openclaw and binance skills into one handoff payload consumed by fusion registry.
---

# OpenClaw + Binance Bridge

Call Binance skill first, then OpenClaw skill, and return both outputs in one object:

```json
{
  "binance": { "...": "normalized market context" },
  "openclaw": { "...": "execution intent" }
}
```

Implementation in code: `core/skill_bridge.py`.
