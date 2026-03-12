---
name: openclaw
description: Convert fusion and confluence outputs into OpenClaw execution intents (execute/watch/block) with deterministic reasons and risk traces.
---

# OpenClaw Skill

Use this skill when the engine needs an explicit action plan from fusion output.

## Inputs
- `confluence.score`
- `decision.allow`
- `decision.vetoes`
- `decision.warnings`

## Output contract
```json
{
  "engine": "openclaw",
  "action": "execute|watch|block",
  "reason": "decision_allow_and_score_ok|decision_allow_but_low_score|fusion_veto",
  "score": 0.0,
  "warnings": [],
  "vetoes": []
}
```

## Rule
1. If `decision.allow=false`, return `block`.
2. If `decision.allow=true` and score >= threshold, return `execute`.
3. Otherwise return `watch`.
